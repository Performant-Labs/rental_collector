# Browser Constraints (The "WebFetch" Rule)

This document defines global operational constraints and user preferences regarding browser-based research and interactions for all AI agents.

## Headless Priority
NEVER use the visual browser tool (`browser_subagent`) for simple data fetching, repository research, or documentation reading. It is slow and disruptive to the user experience.

- **Primary Tool**: Use `read_url_content`. This is the headless equivalent to Claude's "WebFetch" and is significantly faster and less intrusive.
- **Secondary Tool**: Use the terminal `curl` or `wget` for raw file downloads or API interactions.
- **Exception**: The visual `browser_subagent` should ONLY be invoked as a last resort for complex JavaScript-heavy interactions that are impossible to navigate headlessly.
