import json
import time
import requests
import datetime
import urllib.parse
from pathlib import Path 
from typing import Union, List, Dict, Any 
import asyncio 
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


invidious_api_data = {
    'video': [
        'https://invidious.f5.si/',
        'https://yt.omada.cafe/',
        'https://inv.perditum.com/',
        'https://inv.perditum.com/',
        'https://iv.melmac.space/', 
        'https://invidious.nikkosphere.com/',
        'https://iv.duti.dev/',
        'https://youtube.alt.tyil.nl/',
        'https://inv.antopie.org/',
        'https://lekker.gay/',
    ], 
    'playlist': [
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
        'https://iv.duti.dev/',
    ], 
    'search': [
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
    starttime = time.time()
    
    apis_to_try = api_urls
    
    for api in apis_to_try:
        if time.time() - starttime >= max_time - 1:
            break
            
        try:
            res = requests.get(api + 'api/v1' + path, headers=getRandomUserAgent(), timeout=max_api_wait_time)
            
            if res.status_code == requests.codes.ok and isJSON(res.text):
                return res.text
            
        except requests.exceptions.RequestException:
            continue
            
    raise APITimeoutError("All available API instances failed to respond.")
def getEduKey():
    api_url = "https://apis.kahoot.it/media-api/youtube/key"
    try:
        res = requests.get(api_url, headers=getRandomUserAgent(), timeout=max_api_wait_time)
        res.raise_for_status() 
        
        if isJSON(res.text):
            data = json.loads(res.text)
            return data.get("key")
        
    except requests.exceptions.RequestException as e:
        print(f"Kahoot API request failed: {e}")
    except json.JSONDecodeError:
        print("Kahoot API returned non-JSON data.")
    
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

def _get_invidious_streams(t: Dict[str, Any]) -> Dict[str, Union[str, None]]:
    video_formats = t.get('formatStreams', [])
    adaptive_formats = t.get('adaptiveFormats', [])
    
    # 最終的に返すURL
    high_quality_video_url = None
    high_quality_audio_url = None
    standard_video_url = None 
    
    # --- 1. 映像専用ストリーム (Video-Only) の探索 ---
    best_video_only_url = None
    
    def custom_video_sort_key(f: Dict[str, Any]):
        itag = str(f.get('itag', '0'))
        height = int(f.get('height', 0))
        bitrate = int(f.get('bitrate', 0))
        # 優先度1: itag 299または303であれば最高優先度
        priority_itag = 1 if itag in ('299', '303') else 0
        return (priority_itag, height, bitrate)

    video_only_streams = sorted(
        [f for f in adaptive_formats if f.get('acodec') == 'none' and f.get('vcodec') != 'none'],
        key=custom_video_sort_key,
        reverse=True
    )
    
    if video_only_streams:
        best_video_only_url = video_only_streams[0].get('url')
        
    # --- 2. 音声専用ストリーム (Audio-Only) の探索 ---
    best_audio_only_url = None
    audio_only_streams = [f for f in adaptive_formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
    
    if audio_only_streams:
        # itag 140 (M4A/AAC) を優先し、なければビットレート最高を採用
        itag_140_stream = next((f for f in audio_only_streams if f.get('itag') in ('140', 140)), None)
        
        if itag_140_stream:
            best_audio_only_url = itag_140_stream.get('url')
        else:
            sorted_audio_streams = sorted(
                audio_only_streams,
                key=lambda x: int(x.get('bitrate', 0)), 
                reverse=True
            )
            if sorted_audio_streams:
                best_audio_only_url = sorted_audio_streams[0].get('url')
                
    # --- 3. 高画質モードの決定 (映像と音声の両方が必須) ---
    if best_video_only_url and best_audio_only_url:
        # 両方見つかった場合のみ高画質モードを有効化
        high_quality_video_url = best_video_only_url
        high_quality_audio_url = best_audio_only_url
    else:
        # どちらか一方でも見つからなかった場合は、高画質モードを無効化 (Noneのまま)
        
        # --- 4. 映像専用がない場合の代替 (音声付き単一ファイルから最高画質を選ぶ) ---
        # このロジックは、アダプティブ再生が不可能だった場合の「標準画質のリストのトップ」として機能
        best_video_in_formats = sorted(
            [f for f in video_formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none'],
            key=lambda x: int(x.get('height', 0)),
            reverse=True
        )
        if best_video_in_formats:
            # 結合ストリームの最高画質を high_quality_video_url として採用 (high_quality_audio_urlはNoneのまま)
            # これはgetVideoData関数内で'video_urls'の最初の要素として使われる
            high_quality_video_url = best_video_in_formats[0].get('url')

    
    # 5. 360p相当の音声付き単一ファイル (formatStreams) の探索
    standard_streams = sorted(
        [f for f in video_formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none'],
        key=lambda x: int(x.get('height', 0)),
        reverse=True
    )
    
    target_360p = next((f for f in standard_streams if f.get('height') == 360), None)
    if target_360p:
        standard_video_url = target_360p.get('url')
    elif standard_streams:
        standard_video_url = standard_streams[-1].get('url') 

    return {
        "high_quality_video_url": high_quality_video_url,  # 映像・音声両方揃った場合のみ映像専用URLが入る
        "high_quality_audio_url": high_quality_audio_url,  # 映像・音声両方揃った場合のみ音声専用URLが入る
        "standard_video_url": standard_video_url, 
    }
    
async def getVideoData(videoid):
    t_text = await run_in_threadpool(requestAPI, f"/videos/{urllib.parse.quote(videoid)}", invidious_api.video)
    t = json.loads(t_text)
    recommended_videos = t.get('recommendedvideo') or t.get('recommendedVideos') or []
    
    stream_urls = _get_invidious_streams(t)
    
    return [{
        'video_urls': [stream_urls["standard_video_url"]] if stream_urls["standard_video_url"] else list(reversed([i["url"] for i in t["formatStreams"]]))[:2], 
        'high_quality_video_url': stream_urls["high_quality_video_url"],
        'high_quality_audio_url': stream_urls["high_quality_audio_url"],
        'description_html': t["descriptionHtml"].replace("\n", "<br>"), 'title': t["title"],
        'length_text': str(datetime.timedelta(seconds=t["lengthSeconds"])), 'author_id': t["authorId"], 'author': t["author"], 'author_thumbnails_url': t["authorThumbnails"][-1]["url"], 'view_count': t["viewCount"], 'like_count': t["likeCount"], 'subscribers_count': t["subCountText"]
    }, [
        {"video_id": i["videoId"], "title": i["title"], "author_id": i["authorId"], "author": i["author"], "length_text": str(datetime.timedelta(seconds=i["lengthSeconds"])), "view_count_text": i["viewCountText"]}
        for i in recommended_videos
    ]]
    
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
            print(f"API returned no latest videos for channel {channelid}. Treating as failure.")
            t = {}

    except APITimeoutError:
        print(f"Error: Invidious API timeout for channel {channelid}. Using default data.")
    except json.JSONDecodeError:
        print(f"Error: JSON decode failed for channel {channelid}. Using default data.")
    except Exception as e:
        print(f"An unexpected error occurred while fetching channel data for {channelid}: {e}")
        
    
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

def fetch_embed_url_from_external_api(videoid: str) -> str:
    
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

    return run_in_threadpool(sync_fetch)


app = FastAPI()
invidious_api = InvidiousAPI() 

app.mount(
    "/static", 
    StaticFiles(directory=str(BASE_DIR / "static")), 
    name="static"
)

@app.get('/stream/{videoid}', response_class=Response)
async def get_invidious_video_data_raw(videoid: str):

    try:
        t_text = await run_in_threadpool(requestAPI, f"/videos/{urllib.parse.quote(videoid)}", invidious_api.video)
        
        # 取得したJSONテキストをそのままレスポンスとして返す
        return Response(content=t_text, media_type="application/json")
        
    except APITimeoutError as e:
        error_message = json.dumps({"error": f"Invidious API Timeout"})
        return Response(content=error_message, media_type="application/json", status_code=503)
    except Exception as e:
        error_message = json.dumps({"error": f"An unexpected error occurred"})
        return Response(content=error_message, media_type="application/json", status_code=500)
        
@app.get("/api/edu")
async def get_edu_key_route():
    
    key = await run_in_threadpool(getEduKey)
    
    if key:
        return {"key": key}
    else:
        return Response(content='{"error": "Failed to retrieve key from Kahoot API"}', media_type="application/json", status_code=500)

@app.get('/api/stream_high/{videoid}', response_class=HTMLResponse)
async def embed_high_quality_video(request: Request, videoid: str, proxy: Union[str] = Cookie(None)):
    
    try:
        video_data = await getVideoData(videoid)
        stream_data = video_data[0]
        
        video_url = stream_data.get("high_quality_video_url")
        audio_url = stream_data.get("high_quality_audio_url")
        video_title = stream_data.get("title", "Video")
        
        if not video_url:
             return Response("Could not find high-quality video stream (video component) from Invidious API.", status_code=503)
        
    except APITimeoutError as e:
        print(f"Error calling Invidious API: {e}")
        return Response(f"Failed to retrieve high-quality stream URL from Invidious (API Timeout).", status_code=503)
        
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return Response("An unexpected error occurred while retrieving stream data.", status_code=500)

    return templates.TemplateResponse(
        'embed_high.html', 
        {
            "request": request, 
            "video_url": video_url,
            "audio_url": audio_url,
            "video_title": video_title,
            "videoid": videoid,
            "proxy": proxy
        }
    )

@app.get("/api/stream_360p_url/{videoid}")
async def get_360p_stream_url_route(videoid: str):
    try:
        video_data = await getVideoData(videoid)
        standard_url = video_data[0].get('video_urls', [None])[0] 
        
        if standard_url:
            return {"stream_url": standard_url}
        else:
            return Response(content='{"error": "Failed to find 360p stream from Invidious API"}', media_type="application/json", status_code=404)
            
    except Exception as e:
        return Response(content=f'{{"error": "Failed to get stream URL: {e}"}}', media_type="application/json", status_code=503)

@app.get('/api/edu/{videoid}', response_class=HTMLResponse)
async def embed_edu_video(request: Request, videoid: str, proxy: Union[str] = Cookie(None)):
    embed_url = None
    try:
        embed_url = await fetch_embed_url_from_external_api(videoid)
        
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 404:
            return Response(f"Stream URL for videoid '{videoid}' not found.", status_code=404)
        print(f"Error calling external API (HTTP {status_code}): {e}")
        return Response("Failed to retrieve stream URL from external service (HTTP Error).", status_code=503)
        
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
        print(f"Error calling external API: {e}")
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


@app.get('/', response_class=HTMLResponse)
async def home(request: Request, yuzu_access_granted: Union[str] = Cookie(None), proxy: Union[str] = Cookie(None)):
    if yuzu_access_granted != "True":
        return RedirectResponse(url="/gate", status_code=302)
        
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "proxy": proxy
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


@app.get('/watch', response_class=HTMLResponse)
async def video(v:str, request: Request, proxy: Union[str] = Cookie(None)):
    video_data = await getVideoData(v)
    
    high_quality_url = video_data[0].get("high_quality_video_url", "")
    
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
    return RedirectResponse(f"/search?q={tag}", status_code=302)

@app.get("/channel/{channelid}", response_class=HTMLResponse)
async def channel(channelid:str, request: Request, proxy: Union[str] = Cookie(None)):
    t = await getChannelData(channelid)
    return templates.TemplateResponse("channel.html", {"request": request, "results": t[0], "channel_name": t[1]["channel_name"], "channel_icon": t[1]["channel_icon"], "channel_profile": t[1]["channel_profile"], "cover_img_url": t[1]["author_banner"], "subscribers_count": t[1]["subscribers_count"], "tags": t[1]["tags"], "proxy": proxy})

@app.get("/playlist", response_class=HTMLResponse)
async def playlist(list:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    playlist_data = await getPlaylistData(list, str(page))
    return templates.TemplateResponse("search.html", {"request": request, "results": playlist_data, "word": "", "next": f"/playlist?list={list}&page={page + 1}", "proxy": proxy})

@app.get("/comments", response_class=HTMLResponse)
async def comments(request: Request, v:str):
    comments_data = await getCommentsData(v)
    return templates.TemplateResponse("comments.html", {"request": request, "comments": comments_data})

@app.get("/thumbnail")
def thumbnail(v:str):
    return Response(content = requests.get(f"https://img.youtube.com/vi/{v}/0.jpg").content, media_type="image/jpeg")

@app.get("/suggest")
def suggest(keyword:str):
    res_text = requests.get("http://www.google.com/complete/search?client=youtube&hl=ja&ds=yt&q=" + urllib.parse.quote(keyword), headers=getRandomUserAgent()).text
    return [i[0] for i in json.loads(res_text[19:-1])[1]]
