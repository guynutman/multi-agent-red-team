from storage import db

def generate_report(
    storage: Storage,
    campaign_id: int,
    output_path: str,
) -> None:
    """
    Read a campaign's attempts and judgments from storage,
    write a Markdown report to output_path.
    """
    campaign = storage.get_campaign(campaign_id)
    attempts = storage.get_campaign_attempts(campaign_id)