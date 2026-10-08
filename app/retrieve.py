"""Person B retrieval interface."""
def route_claim(claim):
    return ["google_finance","google_news","google"] if claim.domain=="finance" else ["google_scholar","google_news","google"] if claim.domain=="health" else ["google"]
def retrieve_claim(claim,serp): return [],"not_implemented"
