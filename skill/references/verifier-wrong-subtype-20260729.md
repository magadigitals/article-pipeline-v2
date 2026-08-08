# Stage 2c Verifier: Wrong Subtype Detection

The LLM source verifier (`_llm_verify_sources()`) catches sources that pass keyword
matching but are conceptually irrelevant. It was initially designed to catch
biology/gene noise (e.g., Drosophila fly paper with "fear-of-intimacy" in title).

**Expanded to catch wrong-subtype sources (2026-07-29):**

After the phobia-of-being-alone research produced coronaphobia (COVID phobia) and
kinesiophobia (fear of movement) papers — which contain "-phobia" so they keyword-match,
but are about entirely different phobias — the verifier prompt was updated to also
reject sources about "a different subtype/context of the same broad condition."

**Prompt addition:**
```
"a psychological/clinical topic and the source is about cell biology, genetics, "
"animal studies, OR a different subtype/context of the same broad condition "
"(e.g. coronaphobia when the topic is autophobia, or kinesiophobia when the "
"topic is fear of being alone)."
```

**Common wrong-subtype patterns caught:**
- Coronaphobia for autophobia articles
- Kinesiophobia for fear-of-being-alone articles
- Social phobia for specific-phobia articles
- Fear-of-intimacy gene study for psychology articles
- Cancer-patient intimacy studies for fear-of-intimacy articles
