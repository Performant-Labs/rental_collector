"""
shared.listing_html — Generate a self-contained HTML listing page.

Moved here from scraper/rental_search.py so that both the scraper and
wa_export/convert_to_rentals.py can produce identical listing pages
without fragile sys.path hacks.
"""

from __future__ import annotations

from shared.config import MAX_USD, SOURCE_COLORS, TODAY


def _esc(text) -> str:
    """Minimal HTML escaping for text interpolated into HTML."""
    text = str(text)
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def generate_listing_html(listing: dict) -> str:
    """Render a full-page HTML card for a single listing.

    Accepts both raw (Airbnb camelCase) and normalised (snake_case) fields
    and resolves them gracefully.
    """
    # Resolve fields that may differ between raw Airbnb JSON and normalised dicts
    source = str(listing.get("source") or "").strip().lower()
    if not source:
        # Fallback: derive from the Airbnb URL field names used before normalise()
        # ('link' key) or guess from the presence of an airbnb.com URL
        link_val = listing.get("link") or listing.get("url") or ""
        if "airbnb.com" in link_val:
            source = "airbnb"
    url          = listing.get("url") or listing.get("link") or ""
    scraped      = _esc(listing.get("scraped") or TODAY)

    color       = SOURCE_COLORS.get(source, "#444")
    title       = _esc(listing.get("title") or "Untitled")
    price       = listing.get("price_usd") or listing.get("usdPerMonth")
    if price is not None:
        try:
            price = int(price)
        except (TypeError, ValueError):
            price = None
    price_str   = f"${price}" if price else "\u2014"
    bedrooms    = _esc(listing.get("bedrooms") or "")
    location    = _esc(listing.get("location") or "Todos Santos")
    rating      = _esc(listing.get("rating") or "")
    listing_type = _esc(listing.get("listing_type") or listing.get("listingType") or "")
    description  = _esc(listing.get("description") or listing.get("notes") or "")
    amenities    = listing.get("amenities") or []
    checkin      = _esc(listing.get("checkin") or "")
    checkout     = _esc(listing.get("checkout") or "")
    contact      = _esc(listing.get("contact") or "")
    local_photos = listing.get("localPhotos") or []

    source_label = _esc(source.replace("-", " ").title()) if source else "Rental"
    cta_label    = f"View on {source_label} \u2192" if url else ""

    # Photo block
    if local_photos:
        hero = local_photos[0]
        thumbs_html = "".join(
            f'<img src="{p}" alt="" class="thumb" '
            f'onclick="document.querySelector(\'.hero-photo\').src=this.src">'
            for p in local_photos[1:]
        )
        photo_block = (
            f'<img src="{hero}" alt="{title}" class="hero-photo" '
            f'onerror="this.style.display=\'none\'">'
            f'<div class="thumbs">{thumbs_html}</div>'
        )
    else:
        photo_block = '<div class="no-photo">No photos available</div>'

    meta_parts = []
    if listing_type:
        meta_parts.append(f"<span>{listing_type}</span>")
    if bedrooms:
        meta_parts.append(f'<span class="dot">\u00b7</span><span>{bedrooms}</span>')
    if rating:
        meta_parts.append(f'<span class="dot">\u00b7</span><span class="rating">\u2605 {rating}</span>')
    meta_html = "\n            ".join(meta_parts)

    dates_html = ""
    if checkin or checkout:
        dates_html = (
            f'<div class="dates"><p>\U0001f4c5 '
            f'<strong>Check-in:</strong> {checkin} &nbsp;\u2192&nbsp; '
            f'<strong>Checkout:</strong> {checkout}</p></div>'
        )

    amenities_html = ""
    if amenities:
        items = "".join(f"<li>{a}</li>" for a in amenities)
        amenities_html = (
            f'<div class="section"><h3>Amenities</h3>'
            f'<ul class="amenities">{items}</ul></div>'
        )

    contact_html = ""
    if contact:
        contact_html = (
            f'<div class="section"><h3>Contact</h3>'
            f'<p class="desc">{contact}</p></div>'
        )

    desc_html = ""
    if description:
        desc_html = (
            f'<div class="section"><h3>About this place</h3>'
            f'<p class="desc">{description}</p></div>'
        )

    cta_html = (
        f'<a href="{url}" class="cta" target="_blank">{cta_label}</a>'
        if url else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} \u2014 {price_str}/mo</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f7f7f7; color: #222; }}
    .header {{ background: {color}; color: white; padding: 16px 24px; }}
    .header h1 {{ font-size: 14px; font-weight: 400; opacity: 0.9; }}
    .container {{ max-width: 860px; margin: 24px auto; padding: 0 16px; }}
    .hero-photo {{ width: 100%; max-height: 460px; object-fit: cover; border-radius: 12px; display: block; }}
    .no-photo {{ background: #e8e8e8; height: 200px; display: flex; align-items: center; justify-content: center; border-radius: 12px; font-size: 18px; color: #888; }}
    .thumbs {{ display: flex; gap: 8px; margin-top: 8px; overflow-x: auto; }}
    .thumb {{ width: 120px; height: 80px; object-fit: cover; border-radius: 8px; cursor: pointer; flex-shrink: 0; opacity: 0.8; }}
    .thumb:hover {{ opacity: 1; }}
    .info-card {{ background: white; border-radius: 12px; padding: 24px; margin-top: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    .title-row {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }}
    h2 {{ font-size: 22px; font-weight: 700; line-height: 1.3; }}
    .price-tag {{ background: #f0fff4; border: 2px solid #22c55e; border-radius: 10px; padding: 8px 16px; text-align: center; flex-shrink: 0; }}
    .price-tag .amount {{ font-size: 26px; font-weight: 800; color: #16a34a; }}
    .price-tag .label {{ font-size: 11px; color: #666; }}
    .meta {{ display: flex; gap: 16px; margin: 12px 0; flex-wrap: wrap; }}
    .meta span {{ font-size: 14px; color: #555; }}
    .meta .dot {{ color: #ccc; }}
    .rating {{ color: {color}; font-weight: 600; }}
    .section {{ margin-top: 20px; }}
    .section h3 {{ font-size: 16px; font-weight: 600; margin-bottom: 8px; color: #333; }}
    .desc {{ font-size: 14px; line-height: 1.7; color: #444; }}
    .amenities {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 6px; }}
    .amenities li {{ font-size: 13px; color: #555; padding: 4px 0; padding-left: 20px; position: relative; }}
    .amenities li::before {{ content: "\u2713"; position: absolute; left: 0; color: #22c55e; font-weight: bold; }}
    .dates {{ background: #f8faff; border: 1px solid #dde6ff; border-radius: 8px; padding: 12px 16px; margin-top: 8px; }}
    .dates p {{ font-size: 13px; color: #555; }}
    .cta {{ display: block; text-align: center; background: {color}; color: white; padding: 14px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-top: 20px; font-size: 15px; }}
    .cta:hover {{ opacity: 0.88; }}
    .footer {{ text-align: center; font-size: 12px; color: #999; margin: 24px 0; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Todos Santos Rentals \u2014 {source_label} \u00b7 Scraped {scraped} \u00b7 Under ${MAX_USD}/mo</h1>
  </div>
  <div class="container">
    <div style="margin-top:0">
      {photo_block}
    </div>
    <div class="info-card">
      <div class="title-row">
        <div>
          <h2>{title}</h2>
          <div class="meta">
            {meta_html}
          </div>
        </div>
        <div class="price-tag">
          <div class="amount">{price_str}</div>
          <div class="label">/ month</div>
        </div>
      </div>
      {dates_html}
      {desc_html}
      {amenities_html}
      {contact_html}
      {cta_html}
    </div>
    <div class="footer">Scraped {scraped} \u00b7 {location} \u00b7 Source: {source_label}</div>
  </div>
</body>
</html>"""
