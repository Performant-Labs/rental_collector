#!/usr/bin/env python3
"""Unit tests for rental_search.py"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import rental_search as rs


# ── normalise ─────────────────────────────────────────────────────────────────

class TestNormalise(unittest.TestCase):

    def test_canonical_keys_present(self):
        result = rs.normalise({}, "airbnb")
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "photo_url"}
        self.assertEqual(set(result.keys()), expected)

    def test_source_always_overwritten(self):
        raw = {"source": "something-else"}
        self.assertEqual(rs.normalise(raw, "airbnb")["source"], "airbnb")

    def test_maps_usd_per_month(self):
        self.assertEqual(rs.normalise({"usdPerMonth": 1200}, "airbnb")["price_usd"], 1200)

    def test_price_usd_takes_priority_over_usd_per_month(self):
        raw = {"price_usd": 900, "usdPerMonth": 1200}
        self.assertEqual(rs.normalise(raw, "airbnb")["price_usd"], 900)

    def test_maps_link_to_url(self):
        raw = {"link": "https://airbnb.com/rooms/123"}
        self.assertEqual(rs.normalise(raw, "airbnb")["url"], "https://airbnb.com/rooms/123")

    def test_url_takes_priority_over_link(self):
        raw = {"url": "https://example.com", "link": "https://other.com"}
        self.assertEqual(rs.normalise(raw, "airbnb")["url"], "https://example.com")

    def test_maps_listing_type(self):
        raw = {"listingType": "Entire rental unit"}
        self.assertEqual(rs.normalise(raw, "airbnb")["listing_type"], "Entire rental unit")

    def test_notes_falls_back_to_description(self):
        raw = {"notes": "furnished, utilities included"}
        self.assertEqual(rs.normalise(raw, "craigslist")["description"], "furnished, utilities included")

    def test_description_takes_priority_over_notes(self):
        raw = {"description": "nice place", "notes": "fallback"}
        self.assertEqual(rs.normalise(raw, "craigslist")["description"], "nice place")

    def test_amenities_list_preserved(self):
        raw = {"amenities": ["WiFi", "Kitchen"]}
        self.assertEqual(rs.normalise(raw, "airbnb")["amenities"], ["WiFi", "Kitchen"])

    def test_amenities_comma_string_split(self):
        raw = {"amenities": "WiFi, Kitchen, AC"}
        result = rs.normalise(raw, "airbnb")["amenities"]
        self.assertEqual(result, ["WiFi", "Kitchen", "AC"])

    def test_amenities_defaults_to_empty_list(self):
        self.assertEqual(rs.normalise({}, "craigslist")["amenities"], [])

    def test_price_coerced_to_int(self):
        self.assertEqual(rs.normalise({"price_usd": "1100"}, "craigslist")["price_usd"], 1100)

    def test_invalid_price_becomes_none(self):
        self.assertIsNone(rs.normalise({"price_usd": "n/a"}, "craigslist")["price_usd"])

    def test_scraped_defaults_to_today(self):
        result = rs.normalise({}, "airbnb")
        self.assertEqual(result["scraped"], rs.TODAY)

    def test_scraped_preserved_if_present(self):
        result = rs.normalise({"scraped": "2026-01-01"}, "airbnb")
        self.assertEqual(result["scraped"], "2026-01-01")

    def test_location_defaults(self):
        self.assertEqual(rs.normalise({}, "airbnb")["location"], "Todos Santos")

    def test_full_airbnb_info_json(self):
        """Mirrors a real info.json from the Airbnb folders."""
        raw = {
            "title": "Todos Santos Studio",
            "listingType": "Entire rental unit in Todos Santos, Mexico",
            "location": "Todos Santos, Mexico",
            "bedrooms": "1 BR · 2 beds · 1 bath",
            "usdPerMonth": 1339,
            "rating": "4.78 (119 reviews)",
            "description": "A great place.",
            "amenities": ["Kitchen", "WiFi", "AC"],
            "link": "https://www.airbnb.com/rooms/123",
            "checkin": "Nov 1, 2026",
            "checkout": "May 1, 2027",
            "scraped": "2026-04-01",
        }
        result = rs.normalise(raw, "airbnb")
        self.assertEqual(result["title"], "Todos Santos Studio")
        self.assertEqual(result["price_usd"], 1339)
        self.assertEqual(result["url"], "https://www.airbnb.com/rooms/123")
        self.assertEqual(result["listing_type"], "Entire rental unit in Todos Santos, Mexico")
        self.assertEqual(result["amenities"], ["Kitchen", "WiFi", "AC"])
        self.assertEqual(result["checkin"], "Nov 1, 2026")
        self.assertEqual(result["checkout"], "May 1, 2027")


# ── scrape_airbnb_local ───────────────────────────────────────────────────────

class TestScrapeAirbnbLocal(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_folder(self, name, data):
        folder = self._tmp / name
        folder.mkdir()
        (folder / "info.json").write_text(json.dumps(data), encoding="utf-8")

    def test_reads_airbnb_folders(self):
        self._write_folder("airbnb-01-studio-1000usd", {
            "title": "Studio", "usdPerMonth": 1000,
            "link": "https://airbnb.com/rooms/1",
        })
        result = rs.scrape_airbnb_local()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "airbnb")
        self.assertEqual(result[0]["price_usd"], 1000)

    def test_ignores_non_airbnb_folders(self):
        self._write_folder("craigslist-01-studio", {"title": "Studio"})
        result = rs.scrape_airbnb_local()
        self.assertEqual(result, [])

    def test_ignores_folders_without_info_json(self):
        (self._tmp / "airbnb-no-info").mkdir()
        result = rs.scrape_airbnb_local()
        self.assertEqual(result, [])

    def test_filters_over_max(self):
        self._write_folder("airbnb-01-expensive", {"title": "Expensive", "usdPerMonth": 2100})
        result = rs.scrape_airbnb_local()
        self.assertEqual(result, [])

    def test_multiple_folders(self):
        for i in range(3):
            self._write_folder(f"airbnb-0{i}-place-{800+i*100}usd",
                               {"title": f"Place {i}", "usdPerMonth": 800 + i * 100})
        result = rs.scrape_airbnb_local()
        self.assertEqual(len(result), 3)


# ── _parse_price_usd ──────────────────────────────────────────────────────────

class TestParsePriceUsd(unittest.TestCase):

    def test_plain_dollar_amount(self):
        self.assertEqual(rs._parse_price_usd("$1,200/month"), 1200)

    def test_dollar_with_spaces(self):
        self.assertEqual(rs._parse_price_usd("$ 950 per month"), 950)

    def test_nightly_rate_ignored(self):
        self.assertIsNone(rs._parse_price_usd("$75/night"))

    def test_large_dollar_treated_as_mxn(self):
        # $55,000 is above the 4,000 threshold → treated as MXN
        result = rs._parse_price_usd("$55,000")
        self.assertIsNotNone(result)
        self.assertLess(result, 5000)

    def test_craigslist_peso_price(self):
        # $18,000 on Baja Craigslist is MXN → ~$1,028 USD
        result = rs._parse_price_usd("$18,000")
        self.assertIsNotNone(result)
        self.assertEqual(result, round(18000 / 17.5))
        self.assertLess(result, rs.MAX_USD)

    def test_mxn_explicit(self):
        self.assertEqual(rs._parse_price_usd("17500 MXN/month"), 1000)

    def test_pesos_label(self):
        self.assertEqual(rs._parse_price_usd("21000 pesos"), round(21000 / 17.5))

    def test_no_price(self):
        self.assertIsNone(rs._parse_price_usd("Great studio near the beach!"))

    def test_commas_stripped(self):
        self.assertEqual(rs._parse_price_usd("$1,400"), 1400)

    def test_boundary_at_max(self):
        self.assertEqual(rs._parse_price_usd("$2000"), 2000)

    def test_three_digit_dollar(self):
        self.assertEqual(rs._parse_price_usd("$800/mo"), 800)


# ── _listing_key ──────────────────────────────────────────────────────────────

class TestListingKey(unittest.TestCase):

    def test_basic_key(self):
        listing = {"title": "Cozy Studio", "source": "craigslist"}
        self.assertEqual(rs._listing_key(listing), "craigslist|cozy studio")

    def test_normalises_punctuation(self):
        a = rs._listing_key({"title": "Nice place!!!", "source": "X"})
        b = rs._listing_key({"title": "Nice place",    "source": "X"})
        self.assertEqual(a, b)

    def test_truncates_long_title(self):
        key = rs._listing_key({"title": "A" * 100, "source": "S"})
        self.assertLessEqual(len(key.split("|")[1]), 60)

    def test_missing_title(self):
        key = rs._listing_key({"source": "S"})
        self.assertEqual(key, "S|")

    def test_missing_source(self):
        key = rs._listing_key({"title": "Studio"})
        self.assertTrue(key.endswith("|studio"))


# ── merge_listings ────────────────────────────────────────────────────────────

class TestMergeListings(unittest.TestCase):

    def _listing(self, title, source, price=None, url=None):
        return rs.normalise({"title": title, "price_usd": price, "url": url}, source)

    def test_deduplicates_same_title_source(self):
        a = [self._listing("Studio", "craigslist", 1000)]
        b = [self._listing("Studio", "craigslist", 1000)]
        self.assertEqual(len(rs.merge_listings([a, b])), 1)

    def test_keeps_different_sources_different_urls(self):
        """Same title, different sources AND different URLs — both should appear."""
        a = [self._listing("Studio", "craigslist",  1000, url="https://craigslist.org/1")]
        b = [self._listing("Studio", "todossantos", 1000, url="https://todossantos.cc/1")]
        self.assertEqual(len(rs.merge_listings([a, b])), 2)

    def test_deduplicates_same_url_across_sources(self):
        """Regression: Claude web-search rediscovers Airbnb listings already in the
        local database. Listings sharing a URL must collapse regardless of source."""
        url = "https://www.airbnb.com/rooms/12345"
        airbnb = [self._listing("Cozy Studio", "airbnb",     1200, url=url)]
        claude = [self._listing("Cozy Studio", "claude-cli", 1200, url=url)]
        result = rs.merge_listings([airbnb, claude])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "airbnb")

    def test_sorted_by_price(self):
        listings = [
            self._listing("Cheap", "craigslist", 800),
            self._listing("Mid",   "craigslist", 1200),
            self._listing("Low",   "craigslist", 500),
        ]
        result = rs.merge_listings([listings])
        prices = [l["price_usd"] for l in result]
        self.assertEqual(prices, sorted(prices))

    def test_null_price_sorted_last(self):
        listings = [
            self._listing("Unknown", "craigslist", None),
            self._listing("Known",   "craigslist", 1000),
        ]
        result = rs.merge_listings([listings])
        self.assertEqual(result[0]["price_usd"], 1000)
        self.assertIsNone(result[-1]["price_usd"])

    def test_empty_input(self):
        self.assertEqual(rs.merge_listings([[], []]), [])


# ── _parse_claude_output ──────────────────────────────────────────────────────

class TestParseClaudeOutput(unittest.TestCase):

    def _raw_listing(self, title="Test", price=1000):
        return {
            "title": title, "price_usd": price, "bedrooms": "1",
            "location": "Todos Santos", "url": None, "contact": None,
            "description": "", "amenities": [],
        }

    def test_clean_json_array(self):
        raw = json.dumps([self._raw_listing()])
        result = rs._parse_claude_output(raw, "claude-api")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "claude-api")

    def test_strips_markdown_fences(self):
        raw = "```json\n" + json.dumps([self._raw_listing()]) + "\n```"
        self.assertEqual(len(rs._parse_claude_output(raw, "claude-api")), 1)

    def test_strips_plain_fences(self):
        raw = "```\n" + json.dumps([self._raw_listing()]) + "\n```"
        self.assertEqual(len(rs._parse_claude_output(raw, "claude-api")), 1)

    def test_json_embedded_in_prose(self):
        data = json.dumps([self._raw_listing()])
        raw = f"Here are the listings I found:\n{data}\nLet me know if you need more."
        self.assertEqual(len(rs._parse_claude_output(raw, "claude-api")), 1)

    def test_filters_over_max(self):
        listings = [self._raw_listing("Cheap", 900), self._raw_listing("Over", 2100)]
        result = rs._parse_claude_output(json.dumps(listings), "claude-api")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Cheap")

    def test_coerces_price_to_int(self):
        listing = self._raw_listing()
        listing["price_usd"] = "1200"
        result = rs._parse_claude_output(json.dumps([listing]), "claude-api")
        self.assertIsInstance(result[0]["price_usd"], int)

    def test_null_price_kept(self):
        listing = self._raw_listing()
        listing["price_usd"] = None
        result = rs._parse_claude_output(json.dumps([listing]), "claude-api")
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["price_usd"])

    def test_source_set_to_passed_value(self):
        result = rs._parse_claude_output(json.dumps([self._raw_listing()]), "claude-cli")
        self.assertEqual(result[0]["source"], "claude-cli")

    def test_all_canonical_keys_present(self):
        result = rs._parse_claude_output(json.dumps([self._raw_listing()]), "claude-api")
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "photo_url"}
        self.assertEqual(set(result[0].keys()), expected)

    def test_garbage_input_returns_empty(self):
        self.assertEqual(rs._parse_claude_output("nothing useful here", "claude-api"), [])

    def test_empty_string_returns_empty(self):
        self.assertEqual(rs._parse_claude_output("", "claude-api"), [])

    def test_non_list_json_returns_empty(self):
        self.assertEqual(rs._parse_claude_output('{"title": "oops"}', "claude-api"), [])

    def test_skips_non_dict_items(self):
        raw = json.dumps([self._raw_listing(), "not a dict", 42])
        self.assertEqual(len(rs._parse_claude_output(raw, "claude-api")), 1)


# ── search_with_claude_cli ────────────────────────────────────────────────────

class TestSearchWithClaudeCli(unittest.TestCase):

    def _listing_json(self):
        return json.dumps([{
            "title": "CLI Listing", "price_usd": 1100, "bedrooms": "2",
            "location": "Todos Santos", "url": None, "contact": None,
            "description": "", "amenities": [],
        }])

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run")
    def test_successful_call(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout=self._listing_json(), stderr="")
        result = rs.search_with_claude_cli(user_msg="test query")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "claude-cli")

    @patch("rental_search.os.path.isfile", return_value=False)
    def test_binary_not_found(self, _):
        self.assertEqual(rs.search_with_claude_cli(user_msg="test query"), [])

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run")
    def test_nonzero_exit_returns_empty(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth error")
        self.assertEqual(rs.search_with_claude_cli(user_msg="test query"), [])

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run",
           side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120))
    def test_timeout_returns_empty(self, _run, _file):
        self.assertEqual(rs.search_with_claude_cli(user_msg="test query"), [])

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run", side_effect=FileNotFoundError)
    def test_file_not_found_error(self, _run, _file):
        self.assertEqual(rs.search_with_claude_cli(user_msg="test query"), [])

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run")
    def test_passes_print_flag(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        rs.search_with_claude_cli(user_msg="test query")
        args = mock_run.call_args[0][0]
        self.assertIn("--print", args)

    @patch("rental_search.os.path.isfile", return_value=True)
    @patch("rental_search.subprocess.run")
    def test_homebrew_on_path(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        rs.search_with_claude_cli(user_msg="test query")
        env = mock_run.call_args[1]["env"]
        self.assertIn("/opt/homebrew/bin", env["PATH"])


# ── search_with_claude_api ────────────────────────────────────────────────────

class TestSearchWithClaudeApi(unittest.TestCase):

    def _mock_response(self, text):
        block = MagicMock()
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        return resp

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_returns_listings_with_correct_source(self):
        data = json.dumps([{
            "title": "API Listing", "price_usd": 900, "bedrooms": "1",
            "location": "Todos Santos", "url": None, "contact": None,
            "description": "", "amenities": [],
        }])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(data)
        with patch("rental_search.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            mock_anthropic.APIError = Exception
            result = rs.search_with_claude_api(user_msg="test query")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "claude-api")

    def test_no_api_key_returns_empty(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            result = rs.search_with_claude_api(user_msg="test query")
        self.assertEqual(result, [])

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_api_error_returns_empty(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        with patch("rental_search.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            mock_anthropic.APIError = Exception
            result = rs.search_with_claude_api(user_msg="test query")
        self.assertEqual(result, [])

    def test_no_anthropic_package_returns_empty(self):
        with patch.object(rs, "anthropic", None):
            result = rs.search_with_claude_api(user_msg="test query")
        self.assertEqual(result, [])


# ── scrape_craigslist ─────────────────────────────────────────────────────────

class TestScrapeCreaigslist(unittest.TestCase):

    def _make_html(self, title="Studio near plaza", price="$1,100", href="/rooms/123"):
        return f"""
        <ul>
          <li class="cl-static-search-result">
            <a href="{href}">
              <span class="title">{title}</span>
              <span class="price">{price}</span>
            </a>
          </li>
        </ul>
        """

    @patch("rental_search.get_soup")
    def test_parses_listing(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(self._make_html(), "html.parser")
        result = rs.scrape_craigslist()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Studio near plaza")
        self.assertEqual(result[0]["price_usd"], 1100)
        self.assertEqual(result[0]["source"], "craigslist")

    @patch("rental_search.get_soup")
    def test_canonical_keys(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(self._make_html(), "html.parser")
        result = rs.scrape_craigslist()
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "photo_url"}
        self.assertEqual(set(result[0].keys()), expected)

    @patch("rental_search.get_soup")
    def test_filters_over_max(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(self._make_html(price="$2,100"), "html.parser")
        self.assertEqual(rs.scrape_craigslist(), [])

    @patch("rental_search.get_soup", return_value=None)
    def test_network_failure_returns_empty(self, _):
        self.assertEqual(rs.scrape_craigslist(), [])

    @patch("rental_search.get_soup")
    def test_no_matching_items(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup("<ul></ul>", "html.parser")
        self.assertEqual(rs.scrape_craigslist(), [])


# ── scrape_todos_santos_cc ────────────────────────────────────────────────────

class TestScrapeTodosSantosCc(unittest.TestCase):

    def _make_html(self, title="Casa for rent near centro", content="2BR house $900/mo",
                   phone="612-111-2222", email="owner@example.com"):
        return f"""
        <div class="classifieds_container">
          <div class="item">
            <div class="title">{title}</div>
            <div class="content">{content}</div>
            <div class="contact">
              <div class="phone">{phone}</div>
              <div class="email">{email}</div>
            </div>
          </div>
        </div>
        """

    @patch("rental_search.get_soup")
    def test_parses_rental_item(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(self._make_html(), "html.parser")
        result = rs.scrape_todos_santos_cc()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Casa for rent near centro")
        self.assertEqual(result[0]["price_usd"], 900)
        self.assertEqual(result[0]["source"], "todossantos")
        self.assertIn("612-111-2222", result[0]["contact"])
        self.assertIn("owner@example.com", result[0]["contact"])

    @patch("rental_search.get_soup")
    def test_skips_non_rental_items(self, mock_soup):
        from bs4 import BeautifulSoup
        html = """
        <div class="classifieds_container">
          <div class="item">
            <div class="title">Surfboard for sale</div>
            <div class="content">Great condition, $200</div>
          </div>
        </div>
        """
        mock_soup.return_value = BeautifulSoup(html, "html.parser")
        self.assertEqual(rs.scrape_todos_santos_cc(), [])

    @patch("rental_search.get_soup")
    def test_filters_over_max_price(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(
            self._make_html(content="Rental house $2100/month"), "html.parser"
        )
        self.assertEqual(rs.scrape_todos_santos_cc(), [])

    @patch("rental_search.get_soup", return_value=None)
    def test_network_failure_returns_empty(self, _):
        self.assertEqual(rs.scrape_todos_santos_cc(), [])

    @patch("rental_search.get_soup")
    def test_canonical_keys(self, mock_soup):
        from bs4 import BeautifulSoup
        mock_soup.return_value = BeautifulSoup(self._make_html(), "html.parser")
        result = rs.scrape_todos_santos_cc()
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "photo_url"}
        self.assertEqual(set(result[0].keys()), expected)

    @patch("rental_search.get_soup")
    def test_matches_on_content_keyword(self, mock_soup):
        """Item with no rental keyword in title but 'rental' in content should be included."""
        from bs4 import BeautifulSoup
        html = """
        <div class="classifieds_container">
          <div class="item">
            <div class="title">Available now</div>
            <div class="content">Studio apartment for rent $800/month, furnished</div>
          </div>
        </div>
        """
        mock_soup.return_value = BeautifulSoup(html, "html.parser")
        result = rs.scrape_todos_santos_cc()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price_usd"], 800)

    @patch("rental_search.get_soup")
    def test_skips_tour_ad_with_different_keyword_substring(self, mock_soup):
        """Regression: 'different' contains 'rent' as a substring — keyword matching must
        use word boundaries so tour/event ads are not falsely matched.
        Real-world case: LocoMotion city-tour ad on todossantos.cc/classifieds/."""
        from bs4 import BeautifulSoup
        html = """
        <div class="classifieds_container">
          <div class="item">
            <div class="title">City Tour, Tacos &amp; Drinks</div>
            <div class="content">A fun way to explore Todos Santos on a pedal-powered group
              bike, with local stops, great stories, drinks. If you're looking for a
              different way to experience the town, this one's for you. 169usd per person.
              www.locomotionbaja.com</div>
          </div>
        </div>
        """
        mock_soup.return_value = BeautifulSoup(html, "html.parser")
        self.assertEqual(rs.scrape_todos_santos_cc(), [])

    @patch("rental_search.get_soup")
    def test_accepts_casa_listing_with_price(self, mock_soup):
        """'Casa' + a price is a valid weak match and should still be included."""
        from bs4 import BeautifulSoup
        html = """
        <div class="classifieds_container">
          <div class="item">
            <div class="title">Casa Bonita</div>
            <div class="content">Beautiful casa available, $950/month long-term.</div>
          </div>
        </div>
        """
        mock_soup.return_value = BeautifulSoup(html, "html.parser")
        result = rs.scrape_todos_santos_cc()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price_usd"], 950)


# ── save_results / diff_against_previous ──────────────────────────────────────

class TestSaveAndDiff(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, title, price=1000, source="craigslist"):
        return rs.normalise({"title": title, "price_usd": price}, source)

    def test_save_creates_file(self):
        path = rs.save_results([self._listing("Studio")], "craigslist")
        self.assertTrue(path.exists())
        self.assertTrue(path.name.startswith("craigslist-"))

    def test_save_filename_format(self):
        for source in ("airbnb", "craigslist", "todossantos", "claude-api", "claude-cli"):
            path = rs.save_results([self._listing("X", source=source)], source)
            self.assertEqual(path.name, f"{source}-{rs.TODAY}.json")

    def test_save_content_is_valid_json(self):
        listings = [self._listing("Studio")]
        path = rs.save_results(listings, "craigslist")
        saved = json.loads(path.read_text())
        self.assertEqual(saved[0]["title"], "Studio")

    def test_saved_listings_have_canonical_keys(self):
        path = rs.save_results([self._listing("Studio")], "airbnb")
        saved = json.loads(path.read_text())
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "photo_url"}
        self.assertEqual(set(saved[0].keys()), expected)

    def test_diff_no_previous(self):
        rs.diff_against_previous([self._listing("Studio")], "craigslist")  # no exception

    def test_diff_detects_new_listing(self):
        prev = [self._listing("Old Place")]
        (self._tmp / "craigslist-2026-01-01.json").write_text(json.dumps(prev), encoding="utf-8")

        current = [self._listing("Old Place"), self._listing("New Place")]
        rs.save_results(current, "craigslist")

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rs.diff_against_previous(current, "craigslist")
        self.assertIn("1 new listing", buf.getvalue())

    def test_diff_detects_removed_listing(self):
        prev = [self._listing("Gone Place"), self._listing("Still Here")]
        (self._tmp / "craigslist-2026-01-01.json").write_text(json.dumps(prev), encoding="utf-8")

        current = [self._listing("Still Here")]
        rs.save_results(current, "craigslist")

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rs.diff_against_previous(current, "craigslist")
        self.assertIn("1 removed", buf.getvalue())

    def test_diff_only_compares_same_source(self):
        prev = [self._listing("Other Source Place", source="airbnb")]
        (self._tmp / "airbnb-2026-01-01.json").write_text(json.dumps(prev), encoding="utf-8")

        current = [self._listing("New Place")]
        rs.save_results(current, "craigslist")

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rs.diff_against_previous(current, "craigslist")
        self.assertIn("No previous results", buf.getvalue())


# ── _slugify / _folder_name ───────────────────────────────────────────────────

class TestSlugify(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(rs._slugify("Cozy Studio"), "cozy-studio")

    def test_special_chars_removed(self):
        self.assertEqual(rs._slugify("Nice place! (great)"), "nice-place-great")

    def test_truncated_to_40(self):
        self.assertLessEqual(len(rs._slugify("A" * 100)), 40)

    def test_folder_name_format(self):
        listing = {"source": "craigslist", "title": "Beach Studio", "price_usd": 950}
        name = rs._folder_name(listing, 3)
        self.assertTrue(name.startswith("craigslist-03-"))
        self.assertIn("950usd", name)

    def test_folder_name_no_price(self):
        listing = {"source": "craigslist", "title": "Studio", "price_usd": None}
        name = rs._folder_name(listing, 1)
        self.assertIn("noprice", name)


# ── generate_listing_html ─────────────────────────────────────────────────────

class TestGenerateListingHtml(unittest.TestCase):

    def _listing(self, **kwargs):
        base = rs.normalise({"title": "Test Place", "price_usd": 1000,
                              "description": "Nice spot."}, "craigslist")
        base.update(kwargs)
        return base

    def test_contains_title(self):
        html = rs.generate_listing_html(self._listing())
        self.assertIn("Test Place", html)

    def test_contains_price(self):
        html = rs.generate_listing_html(self._listing())
        self.assertIn("$1000", html)

    def test_source_color_applied(self):
        html = rs.generate_listing_html(self._listing())
        self.assertIn(rs.SOURCE_COLORS["craigslist"], html)

    def test_airbnb_color_applied(self):
        listing = self._listing()
        listing["source"] = "airbnb"
        html = rs.generate_listing_html(listing)
        self.assertIn(rs.SOURCE_COLORS["airbnb"], html)

    def test_cta_link_present(self):
        listing = self._listing()
        listing["url"] = "https://craigslist.org/abc"
        html = rs.generate_listing_html(listing)
        self.assertIn("https://craigslist.org/abc", html)

    def test_no_url_no_cta(self):
        listing = self._listing()
        listing["url"] = None
        html = rs.generate_listing_html(listing)
        self.assertNotIn('class="cta"', html)

    def test_amenities_rendered(self):
        listing = self._listing()
        listing["amenities"] = ["WiFi", "Kitchen"]
        html = rs.generate_listing_html(listing)
        self.assertIn("WiFi", html)
        self.assertIn("Kitchen", html)

    def test_local_photos_used(self):
        listing = self._listing()
        listing["localPhotos"] = ["photo_01.jpg", "photo_02.jpg"]
        html = rs.generate_listing_html(listing)
        self.assertIn("photo_01.jpg", html)
        self.assertIn("photo_02.jpg", html)

    def test_no_photos_shows_placeholder(self):
        listing = self._listing()
        listing["localPhotos"] = []
        html = rs.generate_listing_html(listing)
        self.assertIn("No photos available", html)

    def test_unknown_price(self):
        listing = self._listing()
        listing["price_usd"] = None
        html = rs.generate_listing_html(listing)
        self.assertIn("—", html)

    def test_valid_html_structure(self):
        html = rs.generate_listing_html(self._listing())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)


# ── _next_index ───────────────────────────────────────────────────────────────

class TestNextIndex(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_1_when_empty(self):
        self.assertEqual(rs._next_index("craigslist"), 1)

    def test_returns_next_after_existing(self):
        (self._tmp / "craigslist-01-studio-900usd").mkdir()
        (self._tmp / "craigslist-02-house-1100usd").mkdir()
        self.assertEqual(rs._next_index("craigslist"), 3)

    def test_uses_max_not_count_when_gap_exists(self):
        """If folder 02 was deleted, next index should be 3 (max+1), not 2 (count+1)."""
        (self._tmp / "craigslist-01-studio-900usd").mkdir()
        (self._tmp / "craigslist-03-house-1100usd").mkdir()
        self.assertEqual(rs._next_index("craigslist"), 4)

    def test_ignores_other_sources(self):
        (self._tmp / "airbnb-05-place-900usd").mkdir()
        self.assertEqual(rs._next_index("craigslist"), 1)


# ── save_listing_folder ───────────────────────────────────────────────────────

class TestSaveListingFolder(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, title="Beach Studio", price=950, source="craigslist", url=None):
        return rs.normalise({"title": title, "price_usd": price, "url": url}, source)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_creates_folder(self, _):
        folder = rs.save_listing_folder(self._listing(), 1)
        self.assertTrue(folder.is_dir())

    @patch("rental_search.fetch_photos", return_value=[])
    def test_writes_info_json(self, _):
        folder = rs.save_listing_folder(self._listing(), 1)
        info_path = folder / "info.json"
        self.assertTrue(info_path.exists())
        data = json.loads(info_path.read_text())
        self.assertEqual(data["title"], "Beach Studio")

    @patch("rental_search.fetch_photos", return_value=[])
    def test_info_json_has_canonical_keys(self, _):
        folder = rs.save_listing_folder(self._listing(), 1)
        data = json.loads((folder / "info.json").read_text())
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "localPhotos",
                    "photo_url"}
        self.assertEqual(set(data.keys()), expected)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_writes_listing_html(self, _):
        folder = rs.save_listing_folder(self._listing(), 1)
        html_path = folder / "listing.html"
        self.assertTrue(html_path.exists())
        html = html_path.read_text()
        self.assertIn("Beach Studio", html)

    @patch("rental_search.fetch_photos", return_value=["photo_01.jpg"])
    def test_fetches_photos_when_url_present(self, mock_fetch):
        listing = self._listing(url="https://craigslist.org/abc")
        folder = rs.save_listing_folder(listing, 1)
        mock_fetch.assert_called_once()
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["localPhotos"], ["photo_01.jpg"])

    @patch("rental_search.fetch_photos")
    def test_skips_photo_fetch_when_no_url(self, mock_fetch):
        rs.save_listing_folder(self._listing(url=None), 1)
        mock_fetch.assert_not_called()

    @patch("rental_search.fetch_photos", return_value=[])
    def test_folder_name_includes_source_and_price(self, _):
        folder = rs.save_listing_folder(self._listing(), 1)
        self.assertIn("craigslist", folder.name)
        self.assertIn("950usd", folder.name)


class TestIsListingActive(unittest.TestCase):

    def _mock_response(self, status=200, body="Great studio for rent $900/mo"):
        r = MagicMock()
        r.status_code = status
        r.text = body
        return r

    @patch("rental_search.requests.get")
    def test_active_listing_returns_true(self, mock_get):
        mock_get.return_value = self._mock_response(200, "Great studio for rent")
        self.assertTrue(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get")
    def test_404_returns_false(self, mock_get):
        mock_get.return_value = self._mock_response(404, "Not Found")
        self.assertFalse(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get")
    def test_deleted_craigslist_post(self, mock_get):
        mock_get.return_value = self._mock_response(
            200, "This posting has been deleted by its author."
        )
        self.assertFalse(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get")
    def test_expired_craigslist_post(self, mock_get):
        mock_get.return_value = self._mock_response(
            200, "This posting has expired."
        )
        self.assertFalse(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get")
    def test_flagged_craigslist_post(self, mock_get):
        mock_get.return_value = self._mock_response(
            200, "This posting has been flagged for removal."
        )
        self.assertFalse(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get")
    def test_no_longer_available(self, mock_get):
        mock_get.return_value = self._mock_response(200, "This listing is no longer available.")
        self.assertFalse(rs.is_listing_active("https://example.com/listing"))

    @patch("rental_search.requests.get")
    def test_case_insensitive(self, mock_get):
        mock_get.return_value = self._mock_response(200, "THIS POSTING HAS BEEN DELETED")
        self.assertFalse(rs.is_listing_active("https://craigslist.org/abc"))

    @patch("rental_search.requests.get", side_effect=Exception("timeout"))
    def test_network_error_returns_true(self, _):
        # Network errors should not suppress a listing
        self.assertTrue(rs.is_listing_active("https://craigslist.org/abc"))

    def test_no_url_returns_true(self):
        self.assertTrue(rs.is_listing_active(None))
        self.assertTrue(rs.is_listing_active(""))

    @patch("rental_search.requests.get")
    def test_partial_phrase_does_not_trigger(self, mock_get):
        # "a posting has been deleted" doesn't contain "this posting has been deleted"
        mock_get.return_value = self._mock_response(
            200, 'FAQ: "What if a posting has been deleted?"'
        )
        self.assertTrue(rs.is_listing_active("https://craigslist.org/abc"))


class TestScanExisting(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_folder(self, name, data):
        folder = self._tmp / name
        folder.mkdir()
        (folder / "info.json").write_text(json.dumps(data), encoding="utf-8")
        return folder

    def test_indexes_by_url(self):
        self._write_folder("craigslist-01-studio-900usd",
                           {"url": "https://craigslist.org/1", "price_usd": 900,
                            "title": "Studio", "source": "craigslist"})
        index = rs._scan_existing("craigslist")
        self.assertIn("https://craigslist.org/1", index)
        self.assertEqual(index["https://craigslist.org/1"]["price"], 900)

    def test_indexes_by_title_key(self):
        self._write_folder("craigslist-01-studio-900usd",
                           {"url": None, "price_usd": 900,
                            "title": "Studio", "source": "craigslist"})
        index = rs._scan_existing("craigslist")
        tkey = rs._listing_key({"title": "Studio", "source": "craigslist"})
        self.assertIn(tkey, index)

    def test_url_takes_priority_over_title_key(self):
        folder = self._write_folder("craigslist-01-studio-900usd",
                                    {"url": "https://craigslist.org/1", "price_usd": 900,
                                     "title": "Studio", "source": "craigslist"})
        index = rs._scan_existing("craigslist")
        # Both keys should point to the same folder
        tkey = rs._listing_key({"title": "Studio", "source": "craigslist"})
        self.assertEqual(index["https://craigslist.org/1"]["folder"], folder)
        self.assertEqual(index[tkey]["folder"], folder)

    def test_ignores_other_sources(self):
        self._write_folder("airbnb-01-place-900usd",
                           {"url": "https://airbnb.com/1", "price_usd": 900})
        index = rs._scan_existing("craigslist")
        self.assertEqual(index, {})

    def test_empty_when_no_folders(self):
        self.assertEqual(rs._scan_existing("craigslist"), {})

    def test_shared_url_not_indexed_by_url(self):
        """When multiple folders share a URL (e.g. todossantos classifieds page),
        the URL must NOT be used as a dedup key — only title_key dedup applies."""
        shared_url = "https://todossantos.cc/classifieds/"
        self._write_folder("todossantos-01-casa-rent-800usd",
                           {"url": shared_url, "price_usd": 800,
                            "title": "Casa for rent", "source": "todossantos"})
        self._write_folder("todossantos-02-studio-rent-700usd",
                           {"url": shared_url, "price_usd": 700,
                            "title": "Studio for rent", "source": "todossantos"})
        index = rs._scan_existing("todossantos")
        # URL should NOT appear since it's shared
        self.assertNotIn(shared_url, index)
        # Each title_key should still be present
        tkey1 = rs._listing_key({"title": "Casa for rent", "source": "todossantos"})
        tkey2 = rs._listing_key({"title": "Studio for rent", "source": "todossantos"})
        self.assertIn(tkey1, index)
        self.assertIn(tkey2, index)


class TestUpdateListingFolder(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_folder(self, price=900, photos=None):
        folder = self._tmp / "craigslist-01-studio-900usd"
        folder.mkdir()
        info = rs.normalise({"title": "Studio", "price_usd": price, "url": "https://x.com"}, "craigslist")
        info["localPhotos"] = photos or ["photo_01.jpg"]
        (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")
        return folder

    def test_updates_price_in_info_json(self):
        folder = self._make_folder(price=900)
        updated = rs.normalise({"title": "Studio", "price_usd": 1050, "url": "https://x.com"}, "craigslist")
        rs.update_listing_folder(folder, updated, old_price=900)
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 1050)

    def test_preserves_local_photos(self):
        folder = self._make_folder(photos=["photo_01.jpg", "photo_02.jpg"])
        updated = rs.normalise({"title": "Studio", "price_usd": 1050}, "craigslist")
        rs.update_listing_folder(folder, updated, old_price=900)
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["localPhotos"], ["photo_01.jpg", "photo_02.jpg"])

    def test_regenerates_html(self):
        folder = self._make_folder(price=900)
        updated = rs.normalise({"title": "Studio", "price_usd": 1050}, "craigslist")
        rs.update_listing_folder(folder, updated, old_price=900)
        html = (folder / "listing.html").read_text()
        self.assertIn("$1050", html)
        self.assertNotIn("$900", html)

    def test_price_drop_also_updates(self):
        folder = self._make_folder(price=1200)
        updated = rs.normalise({"title": "Studio", "price_usd": 950}, "craigslist")
        rs.update_listing_folder(folder, updated, old_price=1200)
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 950)


class TestSaveListingFolders(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = rs.RESULTS_DIR
        rs.RESULTS_DIR = self._tmp

    def tearDown(self):
        rs.RESULTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, title, url=None, price=900):
        return rs.normalise({"title": title, "price_usd": price, "url": url}, "craigslist")

    def _write_existing(self, title, url, price):
        folder = self._tmp / f"craigslist-01-{rs._slugify(title)}-{price}usd"
        folder.mkdir()
        info = rs.normalise({"title": title, "price_usd": price, "url": url}, "craigslist")
        (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")
        return folder

    @patch("rental_search.is_listing_active", return_value=True)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_creates_new_folder(self, _fetch, _active):
        rs.save_listing_folders([self._listing("New Place", url="https://craigslist.org/new")])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)

    @patch("rental_search.is_listing_active", return_value=True)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_skips_identical_listing(self, _fetch, _active):
        self._write_existing("Same Place", "https://craigslist.org/1", 900)
        rs.save_listing_folders([self._listing("Same Place", url="https://craigslist.org/1", price=900)])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)

    @patch("rental_search.is_listing_active", return_value=True)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_updates_when_price_changes(self, _fetch, _active):
        folder = self._write_existing("Same Place", "https://craigslist.org/1", 900)
        rs.save_listing_folders([self._listing("Same Place", url="https://craigslist.org/1", price=1050)])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 1050)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_dedupes_by_title_when_no_url(self, _):
        self._write_existing("No URL Place", None, 900)
        rs.save_listing_folders([self._listing("No URL Place", url=None, price=900)])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_updates_by_title_when_no_url_and_price_changes(self, _):
        folder = self._write_existing("No URL Place", None, 900)
        rs.save_listing_folders([self._listing("No URL Place", url=None, price=1100)])
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 1100)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_listings_without_url_not_deduped_by_url(self, _):
        listings = [
            self._listing("Place A", url=None),
            self._listing("Place B", url=None),
        ]
        rs.save_listing_folders(listings)
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 2)

    @patch("rental_search.is_listing_active", return_value=False)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_inactive_new_listing_not_saved(self, _fetch, _active):
        rs.save_listing_folders([self._listing("Dead Listing", url="https://x.com/dead")])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 0)

    @patch("rental_search.is_listing_active", return_value=False)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_inactive_price_change_not_updated(self, _fetch, _active):
        folder = self._write_existing("Old Place", "https://x.com/1", 900)
        rs.save_listing_folders([self._listing("Old Place", url="https://x.com/1", price=1100)])
        # Price should remain 900
        data = json.loads((folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 900)

    @patch("rental_search.is_listing_active", return_value=True)
    @patch("rental_search.fetch_photos", return_value=[])
    def test_active_listing_is_saved(self, _fetch, _active):
        rs.save_listing_folders([self._listing("Active Place", url="https://x.com/live")])
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)

    @patch("rental_search.fetch_photos", return_value=[])
    def test_no_url_listing_saved_without_active_check(self, _fetch):
        # Listings without a URL skip the HTTP check and are always saved
        with patch("rental_search.requests.get") as mock_get:
            rs.save_listing_folders([self._listing("No URL", url=None)])
            mock_get.assert_not_called()
        self.assertEqual(len(list(self._tmp.glob("craigslist-*/"))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
