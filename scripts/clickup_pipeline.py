#!/usr/bin/env python3
"""ClickUp integration for Golden Pipeline. Updates tasks at each stage."""
import json, subprocess, sys, os, re
from datetime import datetime
from pathlib import Path

TOKEN = "pk_63073811_1GISZMPO3ZO51EH99G8EEC4M0EE5BKP8"
ASSIGNEE = 63073811

# Author name → ClickUp user ID mapping (resolved from sheet Column B)
AUTHOR_IDS = {
    "maga": 63073811,
    "oghenemaga emmanuel": 63073811,
    "oghenemaga": 63073811,
    "emmanuel": 63073811,
}

SPACES = {
    "MRS": "90171482592",
    "MRS Content Production Hub": "90171482592",
    "Roots Renewal": "90172317195",
    "Roots Renewal Ranch": "90172317195",
    "MRS Arizona": "90174647569",
    "MR Arizona Content Production Hub": "90174647569",
    "Avery's House": "90171503141",
    "AVH Arizona Content Production Hub": "90171503141",
    "AVH Idaho Content Production Hub": "90171503141",
}

FRAMEWORK = Path("/Users/mac/Desktop/Golden writing framework")

# Per-space catch-all list when routing can't place a topic (chosen fallback).
# MRS → "Assets Production" folderless list. Other spaces resolve at runtime.
DEFAULT_LIST = {
    "MRS": "901706059867",
}



def clickup_api(method, endpoint, data=None):
    """Call ClickUp API v2."""
    import urllib.request, urllib.error
    url = f"https://api.clickup.com/api/v2{endpoint}"
    headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if not raw:  # e.g. DELETE → 204 No Content
                return {"ok": True, "status": getattr(resp, "status", 200)}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:200]}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return {"error": "network", "body": str(e)[:200]}

_HIERARCHY_CACHE: dict[str, dict] = {}

def get_space_hierarchy(space_id):
    """Return {folder_name: {"id": folder_id, "lists": {list_name: list_id}}} for a space.
    Cached for the lifetime of the process — data doesn't change mid-run.
    """
    if space_id in _HIERARCHY_CACHE:
        return _HIERARCHY_CACHE[space_id]
    out = {}
    folders = clickup_api("GET", f"/space/{space_id}/folder")
    if isinstance(folders, dict):
        for f in folders.get("folders", []):
            out[f["name"]] = {
                "id": f["id"],
                "lists": {l["name"]: l["id"] for l in f.get("lists", [])},
            }
    _HIERARCHY_CACHE[space_id] = out
    return out


def default_list_id(space_name, hierarchy):
    """Catch-all list for a space when routing can't place the topic."""
    if space_name in DEFAULT_LIST:
        return DEFAULT_LIST[space_name]
    space_id = SPACES.get(space_name)
    # Prefer a folderless list (e.g. "Assets Production")
    fl = clickup_api("GET", f"/space/{space_id}/list")
    if isinstance(fl, dict):
        for l in fl.get("lists", []):
            return l["id"]
    # Last resort: first list of the first folder
    for folder in hierarchy.values():
        for lid in folder["lists"].values():
            return lid
    return None



PROTOCOL_FOLDER_PATTERNS = [
    ("Programs", [
        r"\biop\b", r"\bphp\b", r"intensive outpatient", r"partial hospitalization",
        r"outpatient program", r"virtual iop", r"online iop", r"teen iop",
        r"adolescent iop", r"residential", r"inpatient", r"detox", r"rehab program",
        r"treatment program", r"program\b",
    ]),
    ("Areas", [
        r"\bnear me\b", r"\bmesa\b", r"\bphoenix\b",
        r"\bscottsdale\b", r"\btucson\b", r"\bchandler\b", r"\bgilbert\b",
        r"\btempe\b", r"\barizona\b", r"\baz\b", r"\bcalifornia\b", r"\bca\b",
        r"\bnew york\b", r"\bny\b", r"\bcounty\b", r"\bservice area\b",
    ]),
    ("Crisis", [
        r"suicid", r"overdose", r"self[- ]?harm", r"\bcutting\b", r"\babuse\b",
        r"\bcrisis\b", r"\bemergency\b", r"\bunsafe\b", r"\b911\b", r"\b988\b",
        r"\brunaway\b", r"\bhomeless", r"kicked out", r"\bthrowaway\b",
        r"missing (?:teen|child|kid)",
    ]),
    ("Addictions", [
        r"addiction", r"substance use", r"substance abuse", r"alcohol", r"drug use",
        r"opioid", r"cannabis", r"\bweed\b", r"gaming addiction", r"gambling",
        r"porn addiction", r"screen addiction",
    ]),
    ("Treatments", [
        r"\bcbt\b", r"\bdbt\b", r"\bemdr\b", r"therapy", r"therapist",
        r"medication", r"\bssri\b", r"antidepress", r"antipsychotic",
        r"mood stabilizer", r"naltrexone", r"buprenorphine", r"intervention",
        r"\btreatment\b", r"\bprozac\b", r"\bfluoxetine\b",
        r"\b[a-z][a-z0-9+ -]+\s+vs\s+[a-z][a-z0-9+ -]+\b",
    ]),
    ("Support", [
        r"family", r"parent", r"communication", r"school", r"work", r"job",
        r"relationship", r"support", r"boundar", r"friend", r"caregiver",
        r"\bavoidant\b", r"\bteens?\s+lie\b", r"\bly(?:ing|e)\b",
    ]),
    ("Wellness", [
        r"coping", r"sleep", r"focus", r"mindfulness", r"grounding", r"exercise",
        r"journaling", r"routine", r"relapse prevention", r"stress management",
        r"life skill", r"skills?\b", r"\bgoals?\b", r"panic attack while driving",
        r"panic while driving",
    ]),
    ("Conditions", [
        r"depression", r"anxiety", r"trauma", r"ptsd", r"adhd", r"bipolar",
        r"\bmanic\b", r"\bmania\b", r"\bhypomanic\b", r"\bcyclothymia\b",
        r"ocd", r"autism", r"disorder",
        r"obsess", r"compuls", r"hoarding", r"body dysmorph", r"trichotill",
        r"symptoms?", r"diagnos", r"\bbpd\b", r"borderline", r"behavior",
        r"mood swings", r"mood disorder", r"racing thoughts",
        r"red flags?", r"\bsad\b", r"sadness", r"low mood", r"hopeless",
        r"acting different", r"acting differently", r"teen(?:ager)?s?.*different",
    ]),
]

STOPWORDS = {
    "a", "an", "and", "are", "at", "for", "from", "how", "in", "is", "near",
    "of", "or", "the", "to", "vs", "what", "when", "with", "your",
}

ROUTING_RULES_PATH = Path(__file__).parent / "clickup_routing_rules.json"


def _load_routing_rules():
    """Load ClickUp routing rules from the companion JSON file. Returns defaults on failure."""
    try:
        data = json.loads(ROUTING_RULES_PATH.read_text())
        forced = {item["match"].lower(): (item.get("folder", ""), item.get("list", "")) for item in data.get("forced_routes", [])}
        conflicts = []
        for item in data.get("conflict_resolutions", []):
            conflicts.append({
                "patterns": [str(p).lower() for p in item.get("keyword_patterns", [])],
                "resolved_folder": item.get("resolved_folder", ""),
                "resolved_list": item.get("resolved_list", ""),
                "overrides_folder": item.get("overrides_folder", ""),
                "overrides_list": item.get("overrides_list", ""),
            })
        return forced, conflicts
    except Exception:
        return {}, []


FORCED_ROUTES, CONFLICT_RESOLUTIONS = _load_routing_rules()


def _overrides_existing(list_routes, folder, folder_name):
    if not CONFLICT_RESOLUTIONS:
        return set()
    matched_rules = set()
    for rule in CONFLICT_RESOLUTIONS:
        if (not rule["overrides_folder"] or rule["overrides_folder"].lower() == folder.lower()) \
                and (not rule["overrides_list"] or rule["overrides_list"].lower() == folder_name.lower()):
            matched_rules.add((rule["overrides_folder"], rule["overrides_list"]))
    return matched_rules


def forced_route(text):
    """Return (folder, list) if the topic matches an exact forced route."""
    return FORCED_ROUTES.get(text.lower())


def conflicts_for_keyword(text):
    """Return all (folder, list, conflicting_folder, conflicting_list) tuples for matched rules."""
    results = []
    for rule in CONFLICT_RESOLUTIONS:
        if _text_matches_any(text, rule["patterns"]):
            results.append((
                rule["resolved_folder"],
                rule["resolved_list"],
                rule["overrides_folder"],
                rule["overrides_list"],
            ))
    return results




FOLDER_LIST_PATTERNS = {
    "Conditions": [
        ("Anxiety", [r"anxious", r"anxiety", r"agoraphobia", r"panic", r"phobia"]),
        ("Depression", [r"depress", r"hopeless", r"low mood", r"\bsad\b", r"sadness"]),
        ("Mood Disorders", [r"\bbpd\b", r"borderline", r"bipolar", r"mood"]),
        ("Neuro", [r"adhd", r"autis", r"neurodiverg", r"learning disorder"]),
        ("OCRD", [r"\bocd\b", r"obsess", r"compuls", r"body dysmorph", r"hoarding"]),
        ("Trauma", [r"trauma", r"ptsd", r"attachment disorder", r"reactive attachment"]),
        ("Eating Disorders", [r"eating disorder", r"anorexia", r"bulimia", r"binge eating"]),
        ("Psychosis", [r"psychosis", r"psychotic", r"schizo", r"hallucinat", r"delusion"]),
        ("Behavior", [
            r"behavior", r"defian", r"conduct", r"runaway", r"red flags", r"anger",
            r"acting different", r"acting differently", r"teen(?:ager)?s?.*different",
        ]),
        ("Somatic", [r"somatic", r"body", r"pain", r"health anxiety"]),
        ("Bedwetting & Soiling", [r"bedwet", r"enuresis", r"soiling", r"encopresis"]),
        ("Co-occurring", [r"co[- ]?occurr", r"dual diagnosis", r"substance.*mental", r"mental.*substance"]),
    ],
    "Addictions": [
        ("Behavioral", [r"gaming", r"porn", r"gambling", r"screen", r"internet"]),
        ("Substances", [r"addiction", r"substance", r"alcohol", r"drug", r"opioid", r"weed", r"cannabis", r"nicotine"]),
    ],
    "Addiction": [
        ("Behavioral", [r"gaming", r"porn", r"gambling", r"screen", r"internet"]),
        ("Substances", [r"addiction", r"substance", r"alcohol", r"drug", r"opioid", r"weed", r"cannabis", r"nicotine"]),
    ],
    "Wellness": [
        ("Sleep", [r"sleep", r"insomnia", r"bedtime", r"nightmare"]),
        ("Coping", [r"coping", r"grounding", r"stress", r"calm", r"regulat", r"panic attack while driving", r"panic while driving"]),
        ("Executive Function", [r"focus", r"executive", r"procrastinat", r"motivat", r"organization"]),
        ("Relapse Prevention", [r"relapse", r"craving", r"trigger"]),
        ("Life Skills", [r"goals?", r"life skill", r"routine", r"journaling", r"mindfulness"]),
    ],
    "Treatments": [
        ("Medications", [r"prozac", r"fluoxetine", r"ssri", r"medication", r"antidepress", r"antipsychotic", r"mood stabilizer"]),
        ("Diagnosis", [r"diagnos", r"assessment", r"evaluation", r"screening"]),
        ("Care Options", [r"level of care", r"iop", r"php", r"residential", r"inpatient", r"outpatient", r"rehab", r"program"]),
        ("Therapy", [r"therapy", r"therapist", r"cbt", r"dbt", r"emdr", r"intervention", r"\bvs\b"]),
    ],
    "Support": [
        ("School", [r"school", r"teacher", r"class", r"college"]),
        ("Work", [r"work", r"job", r"career", r"employee"]),
        ("Relationships", [
            r"family", r"parent", r"relationship", r"friend", r"avoidant",
            r"communication", r"boundary", r"\bteens?\s+lie\b", r"\blying\b", r"\blie\b",
        ]),
        ("Sexuality", [r"sexual", r"gender", r"lgbt", r"identity"]),
        ("Finding Care", [r"find", r"finding care", r"provider", r"therapist near", r"help"]),
    ],
    "Crisis": [
        ("Suicide", [r"suicid", r"\b988\b"]),
        ("Overdose", [r"overdose", r"poison"]),
        ("Abuse", [r"abuse", r"unsafe", r"neglect"]),
        ("Runaway", [
            r"runaway", r"homeless", r"kicked out", r"throwaway",
            r"missing (?:teen|child|kid)", r"foster.*runaway",
            r"where (?:do|can).*runaway", r"runaway hotline",
            r"teen(s|ager)?.*(?:left|ran|escaped)",
            r"youth.*homeless", r"homeless.*youth",
        ]),
        ("Self-harm", [r"self[- ]?harm", r"\bcutting\b"]),
    ],
    "Programs": [
        ("List", [r".*"]),
    ],
    "Areas": [
        ("List", [r".*"]),
    ],
}


def _text_matches_any(text, patterns):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def protocol_folder_for_keyword(keyword, folders):
    """Deterministically apply the ClickUp routing protocol in priority order."""
    text = str(keyword or "").lower()
    for desired_folder, patterns in PROTOCOL_FOLDER_PATTERNS:
        if _text_matches_any(text, patterns):
            live_folder = _canonical(desired_folder, folders)
            if live_folder:
                return live_folder, desired_folder
    return None, None


def deterministic_list_for_keyword(keyword, list_names, folder=""):
    """Pick a list inside an already-locked folder without changing folders."""
    if not list_names:
        return None
    if len(list_names) == 1:
        return list_names[0]
    text = str(keyword or "").lower()
    for desired_list, patterns in FOLDER_LIST_PATTERNS.get(folder, []):
        if _text_matches_any(text, patterns):
            live_list = _canonical(desired_list, list_names)
            if live_list:
                return live_list
    return None


def route_list_in_locked_folder(keyword, space_name, folder, list_names):
    """Route only within the protocol-locked folder; never changes folder."""
    if not list_names:
        return None
    return deterministic_list_for_keyword(keyword, list_names, folder=folder)


def _canonical(name, options):
    """Match a model-returned name to a live option, tolerant of case and
    punctuation/spelling drift (e.g. 'Life skills' vs 'Life Skills')."""
    if not name:
        return None
    for o in options:
        if o.lower() == name.lower():
            return o
    import re as _re
    def norm(s):
        return _re.sub(r'[^a-z0-9]', '', s.lower())
    n = norm(name)
    for o in options:
        if norm(o) == n:
            return o
    singular = n[:-1] if n.endswith("s") else n
    for o in options:
        on = norm(o)
        osingular = on[:-1] if on.endswith("s") else on
        if singular == osingular:
            return o
    return None


def _llm_route(keyword, folders, folder_to_lists):
    """Ask DeepSeek via Hermes CLI to pick a valid folder/list from live ClickUp hierarchy.
    Uses the same routing protocol as the Google Sheets AI Router AppScript."""
    try:
        import subprocess, json
        from pathlib import Path
        folder_options = "; ".join(f'"{f}"' for f in folders)
        list_options = ""
        for folder in sorted(folder_to_lists.keys()):
            lists_in_folder = ", ".join(f'"{l}"' for l in folder_to_lists[folder])
            list_options += f'\n- For "{folder}" choose from: {lists_in_folder}'
        prompt = f"""You are a precise ClickUp routing bot. Return ONLY valid JSON with "folder" and "list" keys. Values MUST exactly match the case-sensitive options provided.

KEYWORD TO ROUTE: "{keyword}"

VALID FOLDERS: {folder_options}
VALID LISTS BY FOLDER:{list_options}

ROUTING PROTOCOL — follow in order. The first "yes" determines the folder:
1. Official program or service? -> FOLDER: "Programs"
2. Specific city/state/area? -> FOLDER: "Areas"
3. Urgent safety (suicide, overdose, abuse, self-harm)? -> FOLDER: "Crisis"
4. Formal intervention, therapy, diagnosis, or condition comparison? -> FOLDER: "Treatments"
5. Interpersonal/systemic support (work, family, school)? -> FOLDER: "Support"
6. Practical self-management skill? -> FOLDER: "Wellness"
7. Defining/explaining a diagnosis or disorder? -> FOLDER: "Conditions"

Then pick the LIST within that folder from the valid options above.

Return: {{"folder": "exact folder name", "list": "exact list name"}}"""
        hermes_bin = str(Path.home() / ".local" / "bin" / "hermes")
        cmd = [hermes_bin, "--profile", "research-agent", "-m", "deepseek-v4-flash", "--provider", "deepseek", "-z", prompt]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        # Extract JSON from response
        import re as _re
        json_match = _re.search(r'\{[^{}]*"folder"[^{}]*"list"[^{}]*\}', out, _re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            folder = parsed.get("folder")
            lst = parsed.get("list")
            if folder and lst:
                # Normalize: try live names
                live_folder = _canonical(folder, folders)
                if live_folder:
                    live_list = _canonical(lst, folder_to_lists.get(live_folder, []))
                    if live_list:
                        return live_folder, live_list
        return None, None
    except Exception:
        return None, None


def route_topic(keyword, space_name, hierarchy, skip_llm=False):
    """Classify a keyword into (folder, list) with forced routes, conflict
    resolutions, the protocol router, and an LLM fallback."""
    text = str(keyword or "").lower()
    folders = list(hierarchy.keys())
    folder_to_lists = {f: list(v["lists"].keys()) for f, v in hierarchy.items() if v["lists"]}
    if not folders or not folder_to_lists:
        return None, None

    # 1) forced exact routes take precedence
    forced = forced_route(text)
    if forced:
        folder, list_name = forced
        live_folder = _canonical(folder, folders)
        if live_folder:
            locked_lists = folder_to_lists.get(live_folder, [])
            live_list = _canonical(list_name, locked_lists) or _canonical(list_name, folder_to_lists.get(live_folder, []))
            if live_list:
                return live_folder, live_list
            if locked_lists:
                return live_folder, locked_lists[0]

    # 2) conflict resolutions can redirect or force a folder/list before the
    #    normal protocol router runs, preventing false routing from overlap
    conflicts = conflicts_for_keyword(text)
    if conflicts:
        best = conflicts[0]
        live_folder = _canonical(best[0], folders)
        if live_folder:
            locked_lists = folder_to_lists.get(live_folder, [])
            live_list = _canonical(best[1], locked_lists)
            if live_list:
                return live_folder, live_list

    # 3) protocol router
    protocol_folder, _protocol_label = protocol_folder_for_keyword(text, folders)
    if protocol_folder:
        locked_lists = folder_to_lists.get(protocol_folder, [])
        lst = route_list_in_locked_folder(text, space_name, protocol_folder, locked_lists)
        if lst:
            return protocol_folder, lst
        if locked_lists:
            return protocol_folder, locked_lists[0]
        return protocol_folder, None

    # 4) LLM fallback when rules cannot place the topic
    if skip_llm:
        return None, None
    return _llm_route(text, folders, folder_to_lists)

def create_task(name, space_name, description="", keyword="", folder=None, list_name=None, author=None):
    """Create a ClickUp task, routing it to the right Space/Folder/List.
    Priority: explicit folder+list -> deterministic routing on keyword. No catch-all.
    
    If `author` is provided (matching a key in AUTHOR_IDS), that assignee is used.
    Otherwise falls back to the default ASSIGNEE."""
    space_id = SPACES.get(space_name)
    if not space_id:
        return {"error": f"Unknown space: {space_name}"}

    hierarchy = get_space_hierarchy(space_id)
    list_id = None
    routed = {"folder": folder, "list": list_name}

    # 1. Explicit folder/list (e.g. pre-routed in the sheet)
    if folder and list_name and folder in hierarchy and list_name in hierarchy[folder]["lists"]:
        list_id = hierarchy[folder]["lists"][list_name]
    else:
        # 2. Route the keyword (falls back to the task name)
        rf, rl = route_topic(keyword or name, space_name, hierarchy)
        if rf and rl:
            list_id = hierarchy[rf]["lists"][rl]
            routed = {"folder": rf, "list": rl, "source": "protocol_router"}

    if not list_id:
        return {"error": f"Could not route topic to any ClickUp folder/list for {space_name}: {keyword or name}. All topics must route correctly — no fallback list."}

    # Resolve assignee from author name, falling back to default
    assignee_id = ASSIGNEE
    if author:
        author_norm = _norm_name(author)
        if author_norm in AUTHOR_IDS:
            assignee_id = AUTHOR_IDS[author_norm]

    today_ts = int(datetime.now().timestamp() * 1000)
    task = {
        "name": name,
        "description": description,
        "assignees": [assignee_id],
        "start_date": today_ts,
        "due_date": today_ts,
    }
    # Retry POST up to 3 times — ClickUp API can transiently fail
    result = {"error": "max_retries"}
    for attempt in range(3):
        result = clickup_api("POST", f"/list/{list_id}/task", task)
        if isinstance(result, dict) and "id" in result:
            break
        if isinstance(result, dict) and result.get("error") == "network":
            import time
            time.sleep(2 ** attempt)  # 1s, 2s, 4s backoff
        else:
            break  # non-transient error, don't retry
    if isinstance(result, dict) and "id" in result:
        result["_routed"] = routed
        task_id = result["id"]
        # ClickUp API v2 quirk: POST ignores assignees/dates despite returning them.
        # Retry PUT up to 3 times to set assignee + dates
        for attempt in range(3):
            put_result = clickup_api("PUT", f"/task/{task_id}", {
                "assignees": {"add": [assignee_id], "rem": []},
                "start_date": today_ts,
                "due_date": today_ts,
            })
            if isinstance(put_result, dict) and "error" not in put_result:
                break
            import time
            time.sleep(1)

        # Set custom fields on creation
        task_url = result.get("url", "")
        if task_url:
            update_first_available_custom_field(task_id,
                ["ClickUp URL", "ClickUp Task URL"],
                task_url)
        update_first_available_custom_field(task_id,
            ["Pipeline Stage", "Pipeline Status"],
            "outline generation")
    return result


def _norm_name(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


FIELD_ALIASES = {
    "Draft": ["Draft", "Draft URL", "Google Doc", "Google Doc URL", "Article Draft", "Article Draft URL"],
    "Research Brief": ["Research Brief", "Research Brief URL", "Research", "Research URL"],
    "Outline": ["Outline", "Outline URL"],
    "ClickUp URL": ["ClickUp URL", "ClickUp Task URL", "Task URL", "Task Link"],
    "Published Date": ["Published Date", "Publish Date", "Date Published", "Publication Date", "Published On"],
    "Published URL": ["Published URL", "URL", "Live URL", "Page URL", "Article URL", "Final URL"],
}


def field_name_candidates(field_name):
    names = [field_name]
    names.extend(FIELD_ALIASES.get(field_name, []))
    seen = set()
    out = []
    for name in names:
        key = _norm_name(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def find_custom_field(task, field_name):
    fields = task.get("custom_fields", []) if isinstance(task, dict) else []
    candidates = field_name_candidates(field_name)
    candidate_norms = [_norm_name(name) for name in candidates]
    for f in fields:
        field_norm = _norm_name(f.get("name", ""))
        if field_norm in candidate_norms:
            return f
    # Fallback: tolerate names such as "Final Draft URL" when asked for "Draft".
    # Require candidate norm to be at least 70% of field norm length to avoid
    # accidental substring matches (e.g. "url" matching "taskurl", "finalurl" matching "finalurlslug").
    for f in fields:
        field_norm = _norm_name(f.get("name", ""))
        if any(
            c
            and (c in field_norm or field_norm in c)
            and (min(len(c), len(field_norm)) / max(len(c), len(field_norm)) >= 0.7)
            for c in candidate_norms
        ):
            return f
    return None


def ok_result(result):
    return isinstance(result, dict) and "error" not in result


def update_first_available_custom_field(task_id, field_names, value):
    """Try several custom-field names and return the first successful update."""
    results = []
    for field_name in field_names:
        result = update_custom_field(task_id, field_name, value)
        results.append({"field": field_name, "result": result})
        if ok_result(result):
            return {"ok": True, "field": field_name, "result": result}
    return {"ok": False, "attempts": results}


STATUS_ALIASES = {
    "published": ["published", "Published", "complete", "Complete", "done", "Done"],
    "drafting": ["drafting", "Drafting", "draft", "Draft"],
    "outline generation": ["outline generation", "Outline Generation", "outline", "Outline"],
    "editing & review": ["editing & review", "Editing & Review", "review", "Review"],
}


def resolve_status_for_task(task_id, status):
    """Return the live ClickUp status label that best matches the requested status."""
    candidates = STATUS_ALIASES.get(status, [status])
    candidate_norms = [_norm_name(s) for s in candidates]
    task = clickup_api("GET", f"/task/{task_id}")
    if not isinstance(task, dict) or "error" in task:
        return status

    list_id = (task.get("list") or {}).get("id")
    if not list_id:
        return status
    list_data = clickup_api("GET", f"/list/{list_id}")
    statuses = list_data.get("statuses", []) if isinstance(list_data, dict) else []
    for live_status in statuses:
        name = live_status.get("status", "")
        if _norm_name(name) in candidate_norms:
            return name
    for live_status in statuses:
        name = live_status.get("status", "")
        live_norm = _norm_name(name)
        if any(c and (c in live_norm or live_norm in c) for c in candidate_norms):
            return name
    return status


def update_status(task_id, status):
    """Update ClickUp task status, resolving list-specific casing/names when possible."""
    resolved = resolve_status_for_task(task_id, status)
    result = clickup_api("PUT", f"/task/{task_id}", {"status": resolved})
    if isinstance(result, dict):
        result.setdefault("requested_status", status)
        result.setdefault("resolved_status", resolved)
    return result

def update_custom_field(task_id, field_name, value):
    """Update a custom field on a ClickUp task by tolerant name/alias matching."""
    task = clickup_api("GET", f"/task/{task_id}")
    if "error" in task:
        return task

    field = find_custom_field(task, field_name)
    if not field:
        available = [f.get("name", "") for f in task.get("custom_fields", [])]
        return {"error": f"Custom field not found: {field_name}", "available_fields": available}

    result = clickup_api("POST", f"/task/{task_id}/field/{field['id']}", {"value": value})
    if isinstance(result, dict):
        result.setdefault("field", field.get("name"))
    return result

def convert_to_gdoc(md_path, title):
    """Convert markdown to Google Doc via HTML import and return URL."""
    script = FRAMEWORK / "Active/Scripts/md_to_gdoc_html.py"
    if not script.exists():
        return None
    
    result = subprocess.run(
        ["/Applications/anaconda3/bin/python3.12", str(script), str(md_path), title],
        capture_output=True, text=True, timeout=120
    )
    
    try:
        data = json.loads(result.stdout)
        return data.get("doc_link") or data.get("url") or data.get("documentUrl")
    except:
        for line in result.stdout.split("\n"):
            if "docs.google.com" in line:
                return line.strip()
    return None


def update_doc_fields(task_id, outline_url=None, research_url=None, article_url=None):
    """Update ClickUp custom fields with Google Doc links from pipeline stages.
    
    Call after each stage: outline → "Outline", research → "Research Brief", draft → "Draft".
    """
    if outline_url:
        update_first_available_custom_field(task_id,
            ["Outline", "Outline URL"],
            outline_url)
    if research_url:
        update_first_available_custom_field(task_id,
            ["Research Brief", "Research Brief URL", "Research URL"],
            research_url)
    if article_url:
        update_first_available_custom_field(task_id,
            ["Draft", "Draft URL", "Article Draft", "Article Draft URL"],
            article_url)


def update_sheet(sheet_id, tab, row, col_letter, value):
    """Update a single cell in Google Sheets."""
    script = Path.home() / ".hermes/skills/productivity/google-workspace/scripts/google_api.py"
    range_str = f"{tab}!{col_letter}{row}"
    cmd = [
        "/Applications/anaconda3/bin/python3.12", str(script),
        "sheets", "update", sheet_id, range_str,
        "--values", f'[[{json.dumps(value)}]]'
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass  # Non-blocking — sheet update failure shouldn't crash pipeline

# CLI interface
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "outline", "research", "draft", "edit", "publish", "update-doc"])
    parser.add_argument("--task-id")
    parser.add_argument("--name")
    parser.add_argument("--space")
    parser.add_argument("--folder")
    parser.add_argument("--list")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--md-path")
    parser.add_argument("--title", default="")
    parser.add_argument("--doc-link", default="")
    parser.add_argument("--clickup-url", default="")
    parser.add_argument("--outline", default="")
    parser.add_argument("--research", default="")
    parser.add_argument("--draft", default="")
    parser.add_argument("--sheet-row", type=int)
    parser.add_argument("--sheet-id", default="1m8_kdFOIjX8BXIYEMpvWjA--zE_LbGMO2tR2Vqna4Ps")
    parser.add_argument("--tab", default=datetime.now().strftime("%B"))
    
    args = parser.parse_args()
    
    if args.action == "create":
        # Batch passes --title (not --name); accept either as the task name.
        task_name = args.name or args.title
        result = create_task(
            task_name, args.space, args.description,
            keyword=args.keyword, folder=args.folder, list_name=args.list,
        )
        print(json.dumps(result, indent=2))
        # Update sheet with ClickUp creation result
        if args.sheet_row and args.sheet_id and args.tab:
            task_url = result.get("url", "")
            task_id = result.get("task_id", "")
            if task_url:
                # Write ClickUp URL to column O
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "O", task_url)
                # Write ClickUp Status to column U
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "U", "Created")
                # Write Pipeline Stage to column Q
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "Q", "ClickUp")
                # Write Pipeline Status to column R
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "R", "Completed")
                # Write Live Pipeline to column AJ
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "AJ", "Completed: ClickUp task created")
                print(f"  Sheet updated: row {args.sheet_row}, ClickUp task created — doorbell picks up outline on next tick")
            else:
                # Write failure to sheet so doorbell stops retrying
                error_msg = result.get("error", "") or result.get("reason", "") or "ClickUp API error"
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "U", "Failed")
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "Q", "ClickUp")
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "R", "Failed")
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "S", error_msg[:200])
                print(f"  ⚠ ClickUp creation failed: {error_msg[:100]}")

    elif args.action == "update-doc":
        if args.task_id:
            update_doc_fields(args.task_id, outline_url=args.outline or None,
                              research_url=args.research or None, article_url=args.draft or None)
            print(json.dumps({"ok": True}))
        else:
            print(json.dumps({"ok": False, "error": "No --task-id provided"}))

    elif args.action in ("outline", "research", "draft"):
        if args.md_path and args.task_id:
            url = convert_to_gdoc(args.md_path, args.title)
            field_map = {"outline": "Outline", "research": "Research Brief", "draft": "Draft"}
            field = field_map.get(args.action, "Draft")
            
            field_result = None
            if url:
                field_result = update_first_available_custom_field(args.task_id, [field], url)
            
            status_map = {"outline": "outline generation", "research": "outline generation", "draft": "drafting"}
            status_result = update_status(args.task_id, status_map[args.action])
            print(json.dumps({
                "ok": (not url or field_result.get("ok")) and ok_result(status_result),
                "field": field,
                "url": url,
                "field_result": field_result,
                "status_result": status_result,
            }))
            
            if args.action == "draft" and args.sheet_row:
                update_sheet(args.sheet_id, args.tab, args.sheet_row, "M", url)
    
    elif args.action == "edit":
        if args.task_id:
            update_status(args.task_id, "editing & review")
    
    elif args.action == "publish":
        if args.task_id:
            field_result = None
            clickup_url_result = None
            if args.doc_link:
                field_result = update_first_available_custom_field(
                    args.task_id,
                    ["Published URL", "URL", "Live URL", "Page URL", "Article URL", "Final URL"],
                    args.doc_link,
                )
            if args.clickup_url:
                clickup_url_result = update_first_available_custom_field(
                    args.task_id,
                    ["ClickUp URL", "ClickUp Task URL", "Task URL", "Task Link"],
                    args.clickup_url,
                )
            status_result = update_status(args.task_id, "published")
            ok = ok_result(status_result)
            if args.doc_link:
                ok = ok and bool(field_result and field_result.get("ok"))
            print(json.dumps({
                "ok": ok,
                "task_id": args.task_id,
                "doc_link": args.doc_link,
                "field_result": field_result,
                "clickup_url_result": clickup_url_result,
                "status_result": status_result,
            }, indent=2))
