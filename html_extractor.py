
from bs4 import BeautifulSoup
from pathlib import Path


def extract_html(file_path):

    path = Path(file_path)

    html_content = path.read_text(encoding="utf-8")

    soup = BeautifulSoup(html_content, "html.parser")

    # Extract title
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    # Remove unnecessary elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    # Extract structured content
    content = []

    for element in soup.find_all(["h1", "h2", "h3", "p", "li"]):

        text = element.get_text(" ", strip=True)

        if text:
            content.append({
                "tag": element.name,
                "text": text
            })

    # Combine extracted text
    full_text = "\n".join(
        item["text"] for item in content
    )

    result = {
        "metadata": {
            "title": title,
            "source": str(path.resolve()),
            "format": "HTML",
            "element_count": len(content),
            "character_count": len(full_text)
        },
        "content": content,
        "text": full_text
    }

    return result
