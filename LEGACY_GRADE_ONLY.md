# Legacy browser/API display change

The optional `--headless` local browser mode previously exposed source win rates even though the default native overlay used grades only. Its public data and comparison responses now use explicit allowlists, omit win/pick rates and sample counts, and retain only literal supported grades. Browser lists use name order; comparisons retain the user's three slot positions and do not show a unique-best instruction. Internal normalized source data and existing calculation helpers remain unchanged.

This narrows the displayed data; it is not a claim of Riot certification or approval. Synthetic HTTP and DOM-stub regressions do not establish real-game, Windows, or browser-layout acceptance.
