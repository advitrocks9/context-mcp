"""LinkedIn tools: read-only reads over the stealth browser profile. No post/send."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from context_mcp.linkedin import browser, extract
from context_mcp.toolkit import READ

DEFAULT_SECTIONS = ["experience", "education", "skills"]
_EXPERIENCE = {"internship": "1", "intern": "1", "entry": "2", "associate": "3",
               "mid": "4", "mid-senior": "4", "senior": "4", "director": "5", "executive": "6"}
_JOB_TYPE = {"internship": "I", "intern": "I", "full-time": "F", "fulltime": "F",
             "part-time": "P", "contract": "C", "temporary": "T", "volunteer": "V"}
_DATE = {"day": "r86400", "24h": "r86400", "week": "r604800", "month": "r2592000"}
_REMOTE = {"on-site": "1", "onsite": "1", "remote": "2", "hybrid": "3"}


def register(mcp: FastMCP) -> None:
    @mcp.tool(title="LinkedIn My Profile", annotations=READ)
    async def linkedin_my_profile(
        sections: Annotated[list[str], Field(description="Sections: experience, education, skills, projects, certifications, courses, honors, volunteering, languages.")] = DEFAULT_SECTIONS,
    ) -> dict[str, Any]:
        """Read your own LinkedIn profile in full via the /details/ subpages. Read-only."""
        return await browser.read_profile(None, sections)

    @mcp.tool(title="LinkedIn Get Profile", annotations=READ)
    async def linkedin_get_profile(
        username: Annotated[str, Field(description="Vanity username from the profile URL, e.g. 'williamhgates'.")],
        sections: Annotated[list[str], Field(description="Sections to pull.")] = DEFAULT_SECTIONS,
    ) -> dict[str, Any]:
        """Read a person's profile by username, including full experience/education. Read-only."""
        return await browser.read_profile(username, sections)

    @mcp.tool(title="LinkedIn Search People", annotations=READ)
    async def linkedin_search_people(
        keywords: Annotated[str, Field(description="Search text, e.g. 'quant developer Jane Street Imperial'.")],
    ) -> dict[str, Any]:
        """Search people; returns items [{name, username, profile_url}] plus ranked text. Read-only."""
        return await browser.read_page(f"/search/results/people/?keywords={quote(keywords)}", extract_js=extract.PEOPLE_JS, max_scrolls=6)

    @mcp.tool(title="LinkedIn Search Jobs", annotations=READ)
    async def linkedin_search_jobs(
        keywords: Annotated[str, Field(description="Job search text. Use filter params, not free text, for filters.")],
        location: Annotated[str, Field(description="Optional location, e.g. 'London'.")] = "",
        experience_level: Annotated[str, Field(description="internship, entry, associate, senior, director, executive.")] = "",
        job_type: Annotated[str, Field(description="internship, full-time, part-time, contract, temporary.")] = "",
        date_posted: Annotated[str, Field(description="day, week, month.")] = "",
        remote: Annotated[str, Field(description="on-site, remote, hybrid.")] = "",
        newest_first: Annotated[bool, Field(description="Sort by most recent instead of relevance.")] = False,
    ) -> dict[str, Any]:
        """Search jobs with real LinkedIn filters; returns items [{job_id, title, company, ...}] + text. Read-only."""
        q = f"/jobs/search/?keywords={quote(keywords)}"
        if location:
            q += f"&location={quote(location)}"
        if experience_level and (code := _EXPERIENCE.get(experience_level.lower().strip())):
            q += f"&f_E={code}"
        if job_type and (code := _JOB_TYPE.get(job_type.lower().strip())):
            q += f"&f_JT={code}"
        if date_posted and (code := _DATE.get(date_posted.lower().strip())):
            q += f"&f_TPR={code}"
        if remote and (code := _REMOTE.get(remote.lower().strip())):
            q += f"&f_WT={code}"
        if newest_first:
            q += "&sortBy=DD"
        return await browser.read_page(q, extract_js=extract.JOBS_JS, max_scrolls=5)

    @mcp.tool(title="LinkedIn Feed", annotations=READ)
    async def linkedin_feed() -> dict[str, Any]:
        """Read the home feed as cleaned text. Read-only."""
        return await browser.read_page("/feed/", max_scrolls=6)

    @mcp.tool(title="LinkedIn List Conversations", annotations=READ)
    async def linkedin_conversations() -> dict[str, Any]:
        """List the messaging inbox; returns items [{name, date, snippet, is_inmail}]. Read-only."""
        return await browser.read_page("/messaging/", extract_js=extract.MESSAGES_JS, scroll=False)

    @mcp.tool(title="LinkedIn Read Conversation", annotations=READ)
    async def linkedin_read_conversation(
        name: Annotated[str, Field(description="Participant/thread name from linkedin_conversations.")],
    ) -> dict[str, Any]:
        """Open and read a message thread by participant name. Opening may register a read receipt, so it is not purely passive. Read-only, never sends."""
        return await browser.read_conversation(name)

    @mcp.tool(title="LinkedIn Notifications", annotations=READ)
    async def linkedin_notifications() -> dict[str, Any]:
        """Read notifications as cleaned text. Read-only."""
        return await browser.read_page("/notifications/", max_scrolls=5)
