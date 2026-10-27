# Couple workflow review — v1.9.2

Reviewed the existing Home, checklist, budget/supplier, guest, website/RSVP, stationery, timings, Wedding Day Hub and shared-navigation journeys using the current source and isolated browser sample accounts.

| Friction | Change | Intended benefit |
| --- | --- | --- |
| The grouped menu needs scrolling and users may search for a different name, such as RSVPs or deposits. | Search all existing menu tools by label and common synonyms, with a clear button and no-results message. | Find the existing tool without having to learn its menu group. |
| Adding something starts with finding its section. | Home shortcuts open the existing guest, supplier, task and date editors. | Remove a navigation step from common tasks. |
| An unfinished Home form could be replaced by another quick action. | Confirm before replacing typed changes; retain the normal navigation/unload guards. | Keep unfinished work until the couple chooses to discard it. |
| Printable invitation designs and guest RSVP links are separate tools and easy to confuse. | Put guest list → invitation designs → website/RSVPs → table plan links on the guest page, with a short explanation. | Show where to go next and distinguish print designs from reply links. |
| Revisiting a main-planner section starts at the top. | Restore each section's scroll position within the browser tab, including reload/return, with a memory fallback. | Continue reviewing a longer list without repeatedly scrolling down. |

The update reuses the current editors, server saves, access checks, partner-conflict handling and guest/website data. Navigation and searches do not write to the wedding plan. Browser-tab storage contains only section names and scroll coordinates. Existing read-only previews and expired access remain read only.

The Home next-step and getting-started guide already use the couple's own entries and are retained. Existing section labels, destinations and the four-button mobile dock remain available. These are targeted workflow changes rather than a wholesale layout replacement.

Verification covers real browser widths of 320, 390, 736 and 1280 pixels in light/dark mode, preserved unsaved input, search synonyms/no-results, section return/reload, existing grouped-menu and guest-planning flows, and stationery image upload/crop/download. Python checks cover authentication, data isolation, existing features and the new admin password lifecycle. Production couple accounts were not used for testing.
