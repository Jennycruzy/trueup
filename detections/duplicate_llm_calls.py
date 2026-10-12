"""Dashboard code detection: likely duplicate LLM spans for one provider response."""


def detect(trace):
    seen = set()
    for span in trace.spans:
        if span.type != "LLM":
            continue
        key = (span.attributes.get("gen_ai.response.id"), span.attributes.get("gen_ai.request.model"))
        if key[0] and key in seen:
            return True
        seen.add(key)
    return False
