---
name: news-qa
description: Answer questions about current events and news. Use when the user asks about headlines, breaking news, tech news, world events, or what's happening today.
tools:
  - news__fetch_feed_entries
  - news__fetch_article_content
---

# News & Current Events

Answer questions about current events by fetching news from RSS feeds.

## Approach

1. Identify the topic or category the user is asking about
2. Select the appropriate RSS feed(s) from the list below
3. Use `fetch_feed_entries` to get recent articles (use `limit: 5` for headlines)
4. Optionally use `fetch_article_content` to get full text of a specific article
5. Summarize the key stories in a conversational way

## RSS Feeds by Category

### General News
| Source | Feed URL |
|--------|----------|
| BBC World | `https://feeds.bbci.co.uk/news/world/rss.xml` |
| NPR News | `https://feeds.npr.org/1001/rss.xml` |
| Reuters Top News | `https://www.rss.reuters.com/news/topNews` |
| AP News | `https://rsshub.app/apnews/topics/apf-topnews` |

### Tech News
| Source | Feed URL |
|--------|----------|
| Hacker News | `https://hnrss.org/frontpage` |
| TechCrunch | `https://techcrunch.com/feed/` |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` |
| The Verge | `https://www.theverge.com/rss/index.xml` |

### Business
| Source | Feed URL |
|--------|----------|
| Bloomberg | `https://feeds.bloomberg.com/markets/news.rss` |
| CNBC Top News | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` |

### Science
| Source | Feed URL |
|--------|----------|
| NASA Breaking News | `https://www.nasa.gov/rss/dyn/breaking_news.rss` |
| Science Daily | `https://www.sciencedaily.com/rss/all.xml` |

## Response Guidelines

- Lead with the most significant or relevant story
- Mention the source and approximate time (e.g., "According to BBC earlier today...")
- Summarize 3-5 headlines for "what's happening" questions
- Go deeper on a single story if the user asks about a specific topic
- If a feed fails, try an alternative source in the same category
