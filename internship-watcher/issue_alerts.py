import os
import requests


def create_issue_for_role(role):
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")

    if not token or not repo:
        print("Skipping issue creation: missing GitHub env vars.")
        return

    title = f"New role: {role['company']} — {role['title']}"

    body = f"""
New matching role found.

**Company:** {role['company']}  
**Division:** {role['division']}  
**Role:** {role['title']}  
**Location:** {role['location']}  
**Date found:** {role['date_found']}  

[Apply here]({role['link']})
"""

    url = f"https://api.github.com/repos/{repo}/issues"

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": title,
            "body": body,
            "labels": ["new-role"],
        },
        timeout=20,
    )

    if response.status_code >= 300:
        print(f"Failed to create issue: {response.status_code} {response.text}")