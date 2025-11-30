import json
import time
import requests
import datetime
import urllib.parse
from pathlib import Path 
from typing import Union, List, Dict, Any
import asyncio 
import concurrent.futures
from fastapi import FastAPI, Response, Request, Cookie, Form 
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool 

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates")) 

class APITimeoutError(Exception): pass
def getRandomUserAgent(): return {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36'}
def isJSON(json_str):
    try: json.loads(json_str); return True
    except json.JSONDecodeError: return False

max_time = 10.0
max_api_wait_time = (3.0, 8.0)
failed = "Load Failed"
MAX_RETRIES = 10   
RETRY_DELAY = 3.0 

EDU_STREAM_API_BASE_URL = "https://siawaseok.duckdns.org/api/stream/" 
EDU_VIDEO_API_BASE_URL = "https://siawaseok.duckdns.org/api/video2/"
STREAM_YTDL_API_BASE_URL = "https://yudlp-b34c.onrender.com/stream/" 
SHORT_STREAM_API_BASE_URL = "https://yt-dl-kappa.vercel.app/short/"
BBS_EXTERNAL_API_BASE_URL = "https://server-bbs.vercel.app"


invidious_api_data = {
    # 'video'は使用しないが、他のリストは残す
    'video': [], 
    'playlist': [
        'https://invidious.lunivers.trade/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
        'https://iv.duti.dev/',
    ], 
    'search': [
        'https://invidious.lunivers.trade/',
        'https://inv.vern.cc/',
        'https://yt.thechangebook.org/',
        'https://invidious.vern.cc/',
        'https://invidious.materialio.us/',
        'https://invid-api.poketube.fun/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
        'https://iv.duti.dev/',
    ], 
    'channel': [
        'https://invidious.lunivers.trade/',
        'https://invid-api.poketube.fun/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
        'https://iv.duti.dev/',
    ], 
    'comments': [
        'https://invidious.lunivers.trade/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.duti.dev/',
        'https://iv.melmac.space/',
    ]
}

class InvidiousAPI:
    def __init__(self):
        self.all = invidious_api_data
        self.video = list(self.all['video']); 
        self.playlist = list(self.all['playlist']);
        self.search = list(self.all['search']); 
        self.channel = list(self.all['channel']);
        self.comments = list(self.all['comments']); 
        self.check_video = False

def requestAPI(path, api_urls):
    """
    複数のAPI URLに対してリクエストを並列で実行し、
    最初に成功した応答を返す（動画ページ以外の高速化のための修正を復元）
    """
    
    apis_to_try = api_urls
    
    if not apis_to_try:
        raise APITimeoutError("No API instances configured for this type of request.")
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(apis_to_try)) as executor:
        # 実行のためのタスクをサブミット
        future_to_api = {
            executor.submit(
                requests.get, 
                api + 'api/v1' + path, 
                headers=getRandomUserAgent(), 
                timeout=max_api_wait_time
            ): api for api in apis_to_try
        }
        
        # 完了したタスクから順に結果を取得
        for future in concurrent.futures.as_completed(future_to_api, timeout=max_time):
            try:
                res = future.result()
                
                if res.status_code == requests.codes.ok and isJSON(res.text):
                    # 最初の成功した応答を返す
                    return res.text
                
            except requests.exceptions.RequestException:
                continue # APIが失敗したかタイムアウト。次のタスクの結果を待つ
            except concurrent.futures.TimeoutError:
                # 全てのリクエストがmax_time内に完了しなかった
                break
            
    
    # 全てのリクエストが失敗したか、指定時間内に完了しなかった
    raise APITimeoutError("All available API instances failed to respond or timed out.")

def getEduKey():
    
    api_url = "https://apis.kahoot.it/media-api/youtube/key"
    try:
        res = requests.get(api_url, headers=getRandomUserAgent(), timeout=max_api_wait_time)
        res.raise_for_status() 
        
        if isJSON(res.text):
            data = json.loads(res.text)
            return data.get("key")
        
    except requests.exceptions.RequestException as e:
        
        pass
    except json.JSONDecodeError:
        pass
    
    return None


def formatSearchData(data_dict, failed="Load Failed"):
    if data_dict["type"] == "video": 
        return {"type": "video", "title": data_dict.get("title", failed), "id": data_dict.get("videoId", failed), "author": data_dict.get("author", failed), "published": data_dict.get("publishedText", failed), "length": str(datetime.timedelta(seconds=data_dict.get("lengthSeconds", 0))), "view_count_text": data_dict.get("viewCountText", failed)}
    elif data_dict["type"] == "playlist": 
        return {"type": "playlist", "title": data_dict.get("title", failed), "id": data_dict.get('playlistId', failed), "thumbnail": data_dict.get("playlistThumbnail", failed), "count": data_dict.get("videoCount", failed)}
    elif data_dict["type"] == "channel":
        thumbnail_url = data_dict.get('authorThumbnails', [{}])[-1].get('url', failed)
        thumbnail = "https://" + thumbnail_url.lstrip("http://").lstrip("//") if not thumbnail_url.startswith("https") else thumbnail_url
        return {"type": "channel", "author": data_dict.get("author", failed), "id": data_dict.get("authorId", failed), "thumbnail": thumbnail}
    return {"type": "unknown", "data": data_dict}

def fetch_video_data_from_edu_api(videoid: str):
    
    target_url = f"{EDU_VIDEO_API_BASE_URL}{urllib.parse.quote(videoid)}"
    
    res = requests.get(
        target_url, 
        headers=getRandomUserAgent(), 
        timeout=max_api_wait_time
    )
    res.raise_for_status()
    return res.json()

def format_related_video(related_data: dict) -> dict:
    """
    関連動画のデータをJinjaテンプレートで表示可能な形式に変換する
    """
    
    
    is_playlist = related_data.get("playlistId") and related_data.get("playlistId") != related_data.get("videoId")
    
    
    thumbnail_vid_id = related_data.get('videoId') or related_data.get('playlistId')
    thumbnail_url = f"https://i.ytimg.com/vi/{thumbnail_vid_id}/sddefault.jpg" if thumbnail_vid_id else failed
    
    
    if is_playlist:
        
        return {
            "type": "playlist",
            "title": related_data.get("title", failed), 
            "id": related_data.get('playlistId', failed),
            "author": related_data.get("channel", failed),
            "thumbnail_url": thumbnail_url
        }
    
    return {
        "type": "video", 
        "id": related_data.get("videoId", failed), 
        "video_id": related_data.get("videoId", failed), 
        "title": related_data.get("title", failed), 
        "author_id": related_data.get("channelId", failed),
        "author": related_data.get("channel", failed), 
        "length_text": related_data.get("badge", failed), 
        "view_count_text": related_data.get("views", failed),
        "published_text": related_data.get("uploaded", failed), 
        "thumbnail_url": thumbnail_url
    }

async def getVideoData(videoid):
    
    try:
        t = await run_in_threadpool(fetch_video_data_from_edu_api, videoid)
    except requests.exceptions.RequestException as e:
        
        raise APITimeoutError(f"New video API failed: {e}") from e
    except json.JSONDecodeError as e:
        
        raise APITimeoutError(f"New video API returned invalid JSON: {e}") from e

    author_icon_url = t.get("author", {}).get("thumbnail", failed)
    

    video_details = {
        'video_urls': [], 
        'description_html': t.get("description", {}).get("formatted", failed), 
        'title': t.get("title", failed),
        'author_id': t.get("author", {}).get("id", failed), 
        'author': t.get("author", {}).get("name", failed), 
        'author_thumbnails_url': author_icon_url, 
        'view_count': t.get("views", failed), 
        'like_count': t.get("likes", failed), 
        'subscribers_count': t.get("author", {}).get("subscribers", failed),
        'published_text': t.get("relativeDate", failed),
        "length_text": "" 
    }
    
    
    recommended_videos = [format_related_video(i) for i in t.get('related', [])]

    
    return [video_details, recommended_videos]
    
async def getSearchData(q, page):
    datas_text = await run_in_threadpool(requestAPI, f"/search?q={urllib.parse.quote(q)}&page={page}&hl=jp", invidious_api.search)
    datas_dict = json.loads(datas_text)
    return [formatSearchData(data_dict) for data_dict in datas_dict]

async def getTrendingData(region: str):
    path = f"/trending?region={region}&hl=jp"
    datas_text = await run_in_threadpool(requestAPI, path, invidious_api.search)
    datas_dict = json.loads(datas_text)
    return [formatSearchData(data_dict) for data_dict in datas_dict if data_dict.get("type") == "video"]

async def getChannelData(channelid):
    t = {}
    try:
        
        t_text = await run_in_threadpool(requestAPI, f"/channels/{urllib.parse.quote(channelid)}", invidious_api.channel)
        t = json.loads(t_text)

        
        latest_videos_check = t.get('latestvideo') or t.get('latestVideos')
        if not latest_videos_check:
            
            t = {}

    except APITimeoutError:
        
        pass
    except json.JSONDecodeError:
        
        pass
    except Exception as e:
        
        pass
        
    
    
    latest_videos = t.get('latestvideo') or t.get('latestVideos') or []
    
    
    author_thumbnails = t.get("authorThumbnails", [])
    author_icon_url = author_thumbnails[-1].get("url", failed) if author_thumbnails else failed

    
    author_banner_url = ''
    author_banners = t.get('authorBanners', [])
    if author_banners and author_banners[0].get("url"):
        author_banner_url = urllib.parse.quote(author_banners[0]["url"], safe="-_.~/:")
    
    
    return [[
        {"type":"video", "title": i.get("title", failed), "id": i.get("videoId", failed), "author": t.get("author", failed), "published": i.get("publishedText", failed), "view_count_text": i.get('viewCountText', failed), "length_str": str(datetime.timedelta(seconds=i.get("lengthSeconds", 0)))}
        for i in latest_videos
    ], {
        "channel_name": t.get("author", "チャンネル情報取得失敗"), 
        "channel_icon": author_icon_url, 
        "channel_profile": t.get("descriptionHtml", "このチャンネルのプロフィール情報は見つかりませんでした。"),
        "author_banner": author_banner_url,
        "subscribers_count": t.get("subCount", failed), 
        "tags": t.get("tags", [])
    }]

async def getPlaylistData(listid, page):
    t_text = await run_in_threadpool(requestAPI, f"/playlists/{urllib.parse.quote(listid)}?page={urllib.parse.quote(str(page))}", invidious_api.playlist)
    t = json.loads(t_text)["videos"]
    return [{"title": i["title"], "id": i["videoId"], "authorId": i["authorId"], "author": i["author"], "type": "video"} for i in t]

async def getCommentsData(videoid):
    t_text = await run_in_threadpool(requestAPI, f"/comments/{urllib.parse.quote(videoid)}", invidious_api.comments)
    t = json.loads(t_text)["comments"]
    return [{"author": i["author"], "authoricon": i["authorThumbnails"][-1]["url"], "authorid": i["authorId"], "body": i["contentHtml"].replace("\n", "<br>")} for i in t]


def get_ytdl_formats(videoid: str) -> List[Dict[str, Any]]:
    
    target_url = f"{STREAM_YTDL_API_BASE_URL}{videoid}"
    
    res = requests.get(
        target_url, 
        headers=getRandomUserAgent(), 
        timeout=max_api_wait_time
    )
    res.raise_for_status()
    data = res.json()
    
    formats: List[Dict[str, Any]] = data.get("formats", [])
    if not formats:
        raise ValueError("Stream API response is missing video formats.")
        
    return formats

def get_360p_single_url(videoid: str) -> str:
    
    try:
        formats = get_ytdl_formats(videoid)
        
        # 360pの結合ストリーム (itag 18) を探す
        target_format = next((
            f for f in formats 
            if f.get("itag") == "18" and f.get("url") 
        ), None)
        
        if target_format and target_format.get("url"):
            return target_format["url"]
            
        
        raise ValueError("Could not find a combined 360p stream (itag 18) in the API response.")

    except requests.exceptions.HTTPError as e:
        raise APITimeoutError(f"Stream API returned HTTP error: {e.response.status_code}") from e
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
        raise APITimeoutError(f"Error processing stream API response for 360p: {e}") from e

def fetch_high_quality_streams(videoid: str) -> Dict[str, str]:
    API_URL = f"https://yudlp-b34c.onrender.com/m3u8/{videoid}"

    try:
        response = requests.get(API_URL, timeout=15) 
        response.raise_for_status() 
        data = response.json()
        
        m3u8_formats = data.get('m3u8_formats', [])
        
        if not m3u8_formats:
             raise ValueError("No M3U8 formats found in the API response.")

        def get_height(f):
            resolution_str = f.get('resolution', '0x0')
            try:
                return int(resolution_str.split('x')[-1]) if 'x' in resolution_str else 0
            except ValueError:
                return 0

        m3u8_formats_sorted = sorted(
            [f for f in m3u8_formats if f.get('url')],
            key=get_height,
            reverse=True
        )
        
        if m3u8_formats_sorted:
            best_m3u8 = m3u8_formats_sorted[0]
            
            title = data.get("title", f"Stream for {videoid}")
            resolution = best_m3u8.get('resolution', 'Highest Quality')
            
            return {
                "video_url": best_m3u8["url"],
                "audio_url": "",
                "title": f"[{resolution}] Stream for {title}"
            }

        raise ValueError("Could not find any suitable high-quality stream (M3U8) in the API response after sorting.")

    except requests.exceptions.HTTPError as e:
        raise APITimeoutError(f"Stream API returned HTTP error: {e.response.status_code} for {API_URL}") from e
    except requests.exceptions.Timeout as e:
        raise APITimeoutError(f"Stream API request timed out for {API_URL}") from e
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        raise APITimeoutError(f"Error processing stream API response: {e}") from e
    except ValueError as e:
        raise e

async def fetch_embed_url_from_external_api(videoid: str) -> str:
    
    
    target_url = f"{EDU_STREAM_API_BASE_URL}{videoid}"
    
    def sync_fetch():
        res = requests.get(
            target_url, 
            headers=getRandomUserAgent(), 
            timeout=max_api_wait_time
        )
        res.raise_for_status()
        data = res.json()
        
        embed_url = data.get("url")
        if not embed_url:
            raise ValueError("External API response is missing the 'url' field.")
            
        return embed_url

    return await run_in_threadpool(sync_fetch)

async def fetch_short_data_from_external_api(channelid: str) -> Dict[str, Any]:
    
    target_url = f"{SHORT_STREAM_API_BASE_URL}{urllib.parse.quote(channelid)}"
    
    def sync_fetch():
        res = requests.get(
            target_url, 
            headers=getRandomUserAgent(), 
            timeout=max_api_wait_time 
        )
        res.raise_for_status()
        return res.json()

    return await run_in_threadpool(sync_fetch)

async def fetch_bbs_posts():
    target_url = f"{BBS_EXTERNAL_API_BASE_URL}/posts"
    
    def sync_fetch():
        res = requests.get(
            target_url, 
            headers=getRandomUserAgent(), 
            timeout=max_api_wait_time
        )
        res.raise_for_status()
        return res.json()

    return await run_in_threadpool(sync_fetch)

async def post_new_message(name: str, body: str):
    target_url = f"{BBS_EXTERNAL_API_BASE_URL}/post"
    
    def sync_post():
        res = requests.post(
            target_url, 
            json={"name": name, "body": body},
            headers=getRandomUserAgent(), 
            timeout=max_api_wait_time
        )
        res.raise_for_status()
        return res.json()

    return await run_in_threadpool(sync_post)

    
app = FastAPI()
invidious_api = InvidiousAPI() 

app.mount(
    "/static", 
    StaticFiles(directory=str(BASE_DIR / "static")), 
    name="static"
)


@app.get("/api/edu")
async def get_edu_key_route():
    
    key = await run_in_threadpool(getEduKey)
    
    if key:
        return {"key": key}
    else:
        return Response(content='{"error": "Failed to retrieve key from Kahoot API"}', media_type="application/json", status_code=500)

@app.get('/api/stream_high/{videoid}', response_class=HTMLResponse)
async def embed_high_quality_video(request: Request, videoid: str, proxy: Union[str] = Cookie(None)):
    """
    M3U8優先の最高画質ストリームURLを取得し、埋め込みHTMLをレンダリングする
    """
    try:
        # M3U8優先のロジックを使用
        stream_data = await run_in_threadpool(fetch_high_quality_streams, videoid)
        
    except APITimeoutError as e:
        
        # 503 Service Unavailable (APIアクセス失敗)
        return Response(f"Failed to retrieve high-quality stream URL: {e}", status_code=503)
        
    except Exception as e:
        
        # 500 Internal Server Error (予期せぬエラー)
        return Response("An unexpected error occurred while retrieving stream data.", status_code=500)

    
    return templates.TemplateResponse(
        'embed_high.html', 
        {
            "request": request, 
            # 修正後の fetch_high_quality_streams が返す M3U8 URL (video_url) を渡す
            "video_url": stream_data["video_url"],
            "audio_url": stream_data["audio_url"],
            "video_title": stream_data["title"],
            "videoid": videoid,
            "proxy": proxy
        }
    )

@app.get("/api/stream_360p_url/{videoid}")
async def get_360p_stream_url_route(videoid: str):
    
    try:
        
        url = await run_in_threadpool(get_360p_single_url, videoid)
        return {"stream_url": url}
    except APITimeoutError as e:
        
        
        return Response(content=f'{{"error": "Failed to get stream URL after multiple attempts: {e}"}}', media_type="application/json", status_code=503)
    except Exception as e:
        
        
        return Response(content=f'{{"error": "An unexpected error occurred: {e}"}}', media_type="application/json", status_code=500)

@app.get('/api/edu/{videoid}', response_class=HTMLResponse)
async def embed_edu_video(request: Request, videoid: str, proxy: Union[str] = Cookie(None)):
    
    embed_url = None
    try:
        
        embed_url = await fetch_embed_url_from_external_api(videoid)
        
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 404:
            return Response(f"Stream URL for videoid '{videoid}' not found.", status_code=404)
        
        return Response("Failed to retrieve stream URL from external service (HTTP Error).", status_code=503)
        
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
        
        return Response("Failed to retrieve stream URL from external service (Connection/Format Error).", status_code=503)

    
    return templates.TemplateResponse(
        'embed.html', 
        {
            "request": request, 
            "embed_url": embed_url,
            "videoid": videoid,
            "proxy": proxy
        }
    )

@app.get("/api/short/{channelid}")
async def get_short_data_route(channelid: str):
    
    try:
        data = await fetch_short_data_from_external_api(channelid)
        return data
        
    except Exception as e:
        
        return Response(
            content=f'{{"error": "Failed to retrieve Shorts data from external service: {e!r}"}}', 
            media_type="application/json", 
            status_code=503
        )
        
@app.get("/api/bbs/posts")
async def get_bbs_posts_route():
    try:
        posts_data = await fetch_bbs_posts()
        return posts_data
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        return Response(content=e.response.text, media_type="application/json", status_code=status_code)
    except requests.exceptions.RequestException as e:
        return Response(content=f'{{"detail": "BBS API connection error or timeout: {e!r}"}}', media_type="application/json", status_code=503)
    except Exception as e:
        return Response(content=f'{{"detail": "An unexpected error occurred: {e!r}"}}', media_type="application/json", status_code=500)


@app.post("/api/bbs/post")
async def post_new_message_route(request: Request):
    try:
        
        data = await request.json()
        name = data.get("name", "")
        body = data.get("body", "")
        
        if not body:
            return Response(content='{"detail": "Body is required"}', media_type="application/json", status_code=400)

        # 投稿処理を外部APIに委譲
        post_response = await post_new_message(name, body)
        return post_response
        
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        # 外部APIのエラーをクライアントに返す
        return Response(content=e.response.text, media_type="application/json", status_code=status_code)
    except requests.exceptions.RequestException as e:
        return Response(content=f'{{"detail": "BBS API connection error or timeout: {e!r}"}}', media_type="application/json", status_code=503)
    except Exception as e:
        return Response(content=f'{{"detail": "An unexpected error occurred: {e!r}"}}', media_type="application/json", status_code=500)

@app.get('/', response_class=HTMLResponse)
async def home(request: Request, yuzu_access_granted: Union[str] = Cookie(None), proxy: Union[str] = Cookie(None)):
    if yuzu_access_granted != "True":
        
        return RedirectResponse(url="/gate", status_code=302)
    
    trending_videos = []
    try:
        
        trending_videos = await getTrendingData("jp")
    except Exception as e:
        
        pass
        
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "proxy": proxy,
        "results": trending_videos,
        "word": ""
    })

@app.get('/gate', response_class=HTMLResponse)
async def access_gate_get(request: Request):
    
    return templates.TemplateResponse("access_gate.html", {
        "request": request,
        "message": "アクセスコードを入力してください。"
    })

@app.post('/gate', response_class=RedirectResponse)
async def access_gate_post(request: Request, access_code: str = Form(...)):
    
    
    CORRECT_CODE = "yuzu" 
    
    if access_code == CORRECT_CODE:
        
        response = RedirectResponse(url="/", status_code=302)
        
        expires_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        response.set_cookie(key="yuzu_access_granted", value="True", expires=expires_time.strftime("%a, %d-%b-%Y %H:%M:%S GMT"), httponly=True)
        return response
    else:
        
        return templates.TemplateResponse("access_gate.html", {
            "request": request,
            "message": "無効なアクセスコードです。もう一度入力してください。",
            "error": True
        }, status_code=401)
        
@app.get('/bbs', response_class=HTMLResponse)
async def bbs(request: Request):
    return templates.TemplateResponse("bbs.html", {"request": request})

@app.get('/watch', response_class=HTMLResponse)
async def video(v:str, request: Request, proxy: Union[str] = Cookie(None)):
    
    video_data = await getVideoData(v)
    
    high_quality_url = ""
    
    return templates.TemplateResponse('video.html', {
        "request": request, "videoid": v, "videourls": video_data[0]['video_urls'], 
        "high_quality_url": high_quality_url,
        "description": video_data[0]['description_html'], "video_title": video_data[0]['title'], "author_id": video_data[0]['author_id'], "author_icon": video_data[0]['author_thumbnails_url'], "author": video_data[0]['author'], "length_text": video_data[0]['length_text'], "view_count": video_data[0]['view_count'], "like_count": video_data[0]['like_count'], "subscribers_count": video_data[0]['subscribers_count'], "recommended_videos": video_data[1], "proxy":proxy
    })

@app.get("/search", response_class=HTMLResponse)
async def search(q:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    search_results = await getSearchData(q, page)
    return templates.TemplateResponse("search.html", {"request": request, "results":search_results, "word":q, "next":f"/search?q={q}&page={page + 1}", "proxy":proxy})

@app.get("/hashtag/{tag}")
async def hashtag_search(tag:str):
    return RedirectResponse(f"/search?q={urllib.parse.quote(tag)}", status_code=302)

@app.get("/channel/{channelid}", response_class=HTMLResponse)
async def channel(channelid:str, request: Request, proxy: Union[str] = Cookie(None)):
    
    channel_data = await getChannelData(channelid)
    latest_videos = channel_data[0]
    channel_info = channel_data[1]
    
    shorts_videos = []
    try:
        
        shorts_data = await fetch_short_data_from_external_api(channelid)
        
        
        if isinstance(shorts_data, list):
            shorts_videos = shorts_data
        elif isinstance(shorts_data, dict) and "videos" in shorts_data:
            shorts_videos = shorts_data["videos"]
        
    except Exception as e:
        
        shorts_videos = [] 
        
    return templates.TemplateResponse("channel.html", {
        "request": request, 
        "results": latest_videos, 
        "shorts": shorts_videos,  
        "channel_name": channel_info["channel_name"], 
        "channel_icon": channel_info["channel_icon"], 
        "channel_profile": channel_info["channel_profile"], 
        "cover_img_url": channel_info["author_banner"], 
        "subscribers_count": channel_info["subscribers_count"], 
        "tags": channel_info["tags"], 
        "proxy": proxy
    })

@app.get("/playlist", response_class=HTMLResponse)
async def playlist(list:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    playlist_data = await getPlaylistData(list, str(page))
    return templates.TemplateResponse("search.html", {"request": request, "results": playlist_data, "word": "", "next": f"/playlist?list={list}&page={page + 1}", "proxy": proxy})

@app.get("/comments", response_class=HTMLResponse)
async def comments(request: Request, v:str):
    comments_data = await getCommentsData(v)
    return templates.TemplateResponse("comments.html", {"request": request, "comments": comments_data})

@app.get("/thumbnail")
async def thumbnail(v:str): # <-- 非同期化を復元
    def sync_fetch_thumbnail(video_id: str):
        # YouTubeのサムネイルサーバーから画像を同期的に取得
        res = requests.get(f"https://img.youtube.com/vi/{video_id}/0.jpg", timeout=(1.0, 3.0)) 
        res.raise_for_status()
        return res.content

    try:
        # スレッドプールでブロッキングI/Oを実行
        content = await run_in_threadpool(sync_fetch_thumbnail, v)
        return Response(content=content, media_type="image/jpeg")
    except requests.exceptions.RequestException:
        # 失敗した場合は404を返す
        return Response(status_code=404) 

@app.get("/suggest")
def suggest(keyword:str):
    res_text = requests.get("http://www.google.com/complete/search?client=youtube&hl=ja&ds=yt&q=" + urllib.parse.quote(keyword), headers=getRandomUserAgent()).text
    return [i[0] for i in json.loads(res_text[19:-1])[1]]
