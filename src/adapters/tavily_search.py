from tavily import TavilyClient
from config.config import Config
from src.adapters.logger import logger

class TavilySearchService:
    """
    Wrapper around Tavily's web search API — used when a question needs
    current/general information not covered by our documents or tables.
    """
    def __init__(self):
        self._client = TavilyClient(api_key=Config.TAVILY_API_KEY)
        logger.info('STATUS: Tavily client created successfully')

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Returns a list of search results, each with 'title', 'url', 'content'.
        Returns an empty list if the search fails (caller should handle gracefully).
        """
        try:
            response = self._client.search(
                query=query,
                max_results=max_results,
                search_depth='basic'
            )
            return response.get('results', [])
        except Exception as ex:
            logger.error(f'Tavily search failed for "{query}": {ex}')
            return []

tavily_search = TavilySearchService()