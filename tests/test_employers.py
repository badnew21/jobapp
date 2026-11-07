from jobapp.employers import find_employers, group_businesses, job_links, overpass_query

ELEMENTS = [
    {"tags": {"amenity": "fast_food", "name": "McDonald's", "brand": "McDonald's", "addr:city": "Sebring"}},
    {"tags": {"amenity": "fast_food", "name": "McDonald's", "brand": "McDonald's"}},
    {"tags": {"shop": "supermarket", "name": "Publix", "brand": "Publix", "addr:housenumber": "3133",
              "addr:street": "US 27", "addr:city": "Sebring"}},
    {"tags": {"amenity": "restaurant", "name": "Joe's Diner", "addr:street": "Main St", "addr:city": "Sebring"}},
    {"tags": {"shop": "variety_store", "name": "Dollar General", "brand": "Dollar General"}},
    {"tags": {"amenity": "bank", "name": "Some Bank"}},            # not a category we want
    {"tags": {"shop": "convenience"}},                             # no name
]


def test_grouping():
    emps = group_businesses(ELEMENTS)
    names = [e.name for e in emps]
    assert names[0] == "McDonald's" and emps[0].locations == 2 and emps[0].is_chain
    assert "Some Bank" not in names and len(emps) == 4
    assert names[-1] == "Joe's Diner" and not emps[-1].is_chain        # local places after chains
    publix = next(e for e in emps if e.name == "Publix")
    assert publix.category == "Grocery" and publix.address == "3133 US 27, Sebring"


def test_query_and_links():
    q = overpass_query(27.49, -81.44, 25)
    assert "around:40233,27.49,-81.44" in q and "supermarket" in q and "fast_food" in q
    links = job_links("Publix", "33870", 25)
    assert links["Indeed"] == "https://www.indeed.com/jobs?q=%22Publix%22&l=33870&radius=25"
    assert "Publix+jobs+near+33870" in links["Google jobs"]


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("get", url, params, headers))
        return FakeResp([{"lat": "27.49", "lon": "-81.44"}])

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("post", url, data, headers))
        return FakeResp({"elements": ELEMENTS})


def test_find_employers(tmp_path, monkeypatch):
    import jobapp.employers as E
    monkeypatch.setattr(E, "CACHE_PATH", tmp_path / "geo.json")
    s = FakeSession()
    emps = find_employers("33870", 25, s)
    assert len(emps) == 4
    assert s.calls[0][2]["postalcode"] == "33870" and "JobHelper" in s.calls[0][3]["User-Agent"]
    find_employers("33870", 25, s)
    assert [c[0] for c in s.calls] == ["get", "post", "post"]       # ZIP lookup is cached


def test_employer_name_search_keeps_their_jobs():
    from jobapp.search import Job, SearchOptions, is_relevant, search_terms

    terms = search_terms(SearchOptions(industries=["Any"], extra_keywords="Publix, Dollar General"))
    assert terms == ["Publix", "Dollar General"]
    clerk = Job(id="1", source="x", title="Front Service Clerk", company="Publix Super Markets",
                location="", description="Bag groceries.", url="")
    other = Job(id="2", source="x", title="Front Service Clerk", company="Winn-Dixie",
                location="", description="Bag groceries.", url="")
    assert is_relevant(clerk, terms) and not is_relevant(other, terms)
