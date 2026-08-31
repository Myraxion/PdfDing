from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

from django.urls import reverse


def process_raw_search_query(raw_search_query: str) -> tuple[str, list[str]]:
    """
    Process the raw search query.

    Example input: #tag1 #tag2 searchstring1 searchstring2
    Example output: ('searchstring1 searchstring2', ['tag1', 'tag2'])
    """

    search = []
    tags = []

    if raw_search_query:
        split_query = raw_search_query.split(sep=' ')

        for query in split_query:
            if query.startswith('#'):
                # ignore hashtags only
                if len(query) > 1:
                    tags.append(query[1:])
            elif query:
                # strip and remove '#' and '&' that to not belong to tags search, as a hashtag will cause the rest of
                # the search to be ignored
                query = query.replace('#', '').replace('&', '')
                search.append(query.strip().replace('#', ''))

    search = ' '.join(search)

    return search, tags


def construct_search_and_tag_queries(
    new_search_query: str, remove_tag_query: str, old_tags_str: str, old_search: str
) -> tuple[str, list[str]]:
    """
    Construct the search and tag queries for the overview pages.

    - Tags in "new_search_query" are always added to the existing ones. A Tag that should be removed, is specified via
    "remove_tag_query".
    - Adding or removing tags should not change the existing search
    - If no search and tag inputs are provided the search is reset
    """

    new_search, new_tags = process_raw_search_query(new_search_query)

    old_tags = []
    if old_tags_str:
        old_tags = old_tags_str.split(' ')

    # if there is a new search use it. if there is no tag action we use the new search (which will be empty and resets
    # the search)
    if new_search or not (new_tags or remove_tag_query):
        search = new_search
    # the old search is only kept if there is tag action and no new search
    else:
        search = old_search

    search = search.replace(' ', '+')

    # add new tags to old tags and remove tag if specified
    tags = old_tags + [new_tag for new_tag in new_tags if new_tag not in old_tags]
    tags = [tag for tag in tags if tag != remove_tag_query]

    return search, tags


def construct_query_overview_url(
    referer_url: str,
    search_query: str,
    special_selection_query: str,
    remove_tag_query: str,
    obj_name: str,
) -> str:
    """Constructs the overview url after performing a search in the overview pages."""

    parsed_referer_url = urlparse(referer_url)
    query_parameters = parse_qs(parsed_referer_url.query)

    # special selection, and searching are never performed at the same time, thus we can use if ... elif
    if special_selection_query:
        query_parameters['selection'] = [special_selection_query]
    else:
        referer_tags = query_parameters.get('tags', [''])[0]
        referer_search = query_parameters.get('search', [''])[0]
        search, tags = construct_search_and_tag_queries(search_query, remove_tag_query, referer_tags, referer_search)

        query_parameters['search'] = [search]
        query_parameters['tags'] = tags

    query_string = '&'.join(
        f'{key}={"+".join(query)}' for key, query in query_parameters.items() if query not in [[], ['']]
    )

    overview_url = reverse(f'{obj_name}_overview')

    if query_string:
        overview_url = f'{overview_url}?{query_string}'

    return overview_url


class FuzzyMatch:
    @classmethod
    def is_fuzzy_match(cls, search: str, b: str) -> bool:
        """Check if the search is a fuzzy match of string b"""

        if search in b:
            match = True
        else:
            match = False

            # blanks to be considered junk
            sequence_matcher = SequenceMatcher(lambda x: x == ' ', search, b)
            ratio = sequence_matcher.ratio()

            if ratio > 0.6:
                # using a low ratio is bit conservative but we do not want too many false positives
                match = True
            else:
                partial_ratio = cls.get_partial_ratio(search, b)

                # using a low ratio is bit conservative but we do not want too many false positives
                if partial_ratio > 0.7:
                    match = True
        return match

    @classmethod
    def get_partial_ratio(cls, search: str, b: str) -> float:
        """Get the partial match ratio between two strings using difflib's sequence_matcher"""

        search_words = search.split()

        number_of_search_words = len(search_words)
        b_words = b.split()
        number_of_words_b = len(b_words)

        ratio = 0

        if number_of_words_b > number_of_search_words:
            partials = cls.get_partials(b_words, number_of_search_words)

            for partial in partials:
                sequence_matcher = SequenceMatcher(lambda x: x == ' ', search, partial)
                ratio = max(ratio, sequence_matcher.ratio())

        return ratio

    @staticmethod
    def get_partials(b_words: list[str], number_of_words_a: int) -> list[str]:
        """
        Get partial sentences of a list of words.

        E.g. b_words = [one two three four]
        number_of_words_a: 2 -> ['one two', 'two three', 'three four']
        number_of_words_a: 3 -> ['one two three', 'two three four']
        """

        number_of_words_b = len(b_words)

        if number_of_words_a > number_of_words_b or number_of_words_a < 1:
            return []

        else:
            partials = [
                (' ').join(b_words[i : i + number_of_words_a])  # noqa: E203
                for i in range(number_of_words_b - number_of_words_a + 1)
            ]

            return partials
