from pathlib import Path


def render_open_roles(roles):
    lines = [
        "# Open Roles",
        "",
        "| Company | Division | Role | Location | Date Found | Link |",
        "|---|---|---|---|---|---|",
    ]

    for role in roles:
        lines.append(
            f"| {role['company']} | {role['division']} | "
            f"{role['title']} | {role['location']} | "
            f"{role['date_found']} | [Apply]({role['link']}) |"
        )

    Path("open_roles.md").write_text("\n".join(lines))