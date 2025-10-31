import aiohttp


async def fetch_content(url: str) -> str:
    """Fetch content from provided URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    print(f"Failed to fetch content: {response.status}")
                    return ""
    except Exception as e:
        print(f"Error fetching content: {e}")
        return ""
