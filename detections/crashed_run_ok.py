"""Dashboard code detection: a failed child under an OK root."""


def detect(trace):
    roots = [span for span in trace.spans if not span.parent_id]
    children = [span for span in trace.spans if span.parent_id]
    return any(root.status == "OK" for root in roots) and any(span.status == "ERROR" for span in children)
