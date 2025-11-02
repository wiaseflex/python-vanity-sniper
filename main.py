import aiohttp
import asyncio
import json
import pycurl
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

TOKEN = ""
TARGET_GUILD_ID = ""
MFA_TOKEN = ""
REQUEST_COUNT = 5

guilds = {}
executor = ThreadPoolExecutor(max_workers=REQUEST_COUNT)

curl_pool = []

def init_curl_pool():
    global curl_pool
    for _ in range(REQUEST_COUNT):
        curl = pycurl.Curl()
        # Sabit ayarlar
        curl.setopt(pycurl.NOSIGNAL, 1)
        curl.setopt(pycurl.CONNECTTIMEOUT, 3)  
        curl.setopt(pycurl.TIMEOUT, 5)  
        curl.setopt(pycurl.SSL_VERIFYPEER, 0)
        curl.setopt(pycurl.SSL_VERIFYHOST, 0)
        curl.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_3)
        curl.setopt(pycurl.TCP_NODELAY, 1)
        curl.setopt(pycurl.HTTP_VERSION, pycurl.CURL_HTTP_VERSION_2_0)
        
        try:
            curl.setopt(pycurl.PIPEWAIT, 1)  
        except:
            pass
        
        try:
            curl.setopt(pycurl.TCP_FASTOPEN, 1)  
        except:
            pass
        
        curl_pool.append(curl)

def load_mfa_token():
    global MFA_TOKEN
    try:
        with open("mfa.txt", "r", encoding="utf-8") as f:
            new_token = f.read().strip()
            if new_token != MFA_TOKEN:
                MFA_TOKEN = new_token
    except Exception as e:
        print(f"[ERROR] MFA token okunamadı: {e}")

async def periodic_mfa_loader():
    while True:
        load_mfa_token()
        await asyncio.sleep(10)

def send_curl_request(vanity_code, index):
    curl = curl_pool[index]
    buffer = BytesIO()
    
    headers = [
        f'Authorization: {TOKEN}',
        f'X-Discord-MFA-Authorization: {MFA_TOKEN}',
        'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Super-Properties: eyJicm93c2VyIjoiRmlyZWZveCIsImJyb3dzZXJfdXNlcl9hZ2VudCI6IkZpcmVmb3gifQ==',
        'Content-Type: application/json',
        'Connection: keep-alive'
    ]
    
    payload = json.dumps({"code": vanity_code}, separators=(',', ':')) 

    curl.setopt(pycurl.URL, f'https://canary.discord.com/api/v6/guilds/{TARGET_GUILD_ID}/vanity-url')
    curl.setopt(pycurl.CUSTOMREQUEST, 'PATCH')
    curl.setopt(pycurl.HTTPHEADER, headers)
    curl.setopt(pycurl.POSTFIELDS, payload)
    curl.setopt(pycurl.WRITEDATA, buffer)
    
    try:
        curl.perform()
        response = buffer.getvalue().decode('utf-8')
        try:
            data = json.loads(response)
            if 'code' in data or 'message' in data:
                print(f"[{index}] {json.dumps(data)}")
        except:
            pass
    except:
        pass

async def extreme_snipe(vanity_code):
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(executor, send_curl_request, vanity_code, i) for i in range(REQUEST_COUNT)]
    await asyncio.gather(*tasks, return_exceptions=True)

async def websocket_handler():
    global guilds
    
    while True:
        try:
            # WebSocket connection pooling
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                force_close=False,
                enable_cleanup_closed=True
            )
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.ws_connect(
                    'wss://gateway-us-east1-b.discord.gg',
                    compress=None,
                    max_msg_size=0,
                    ssl=False,
                    heartbeat=30  
                ) as ws:
                    heartbeat_task = None
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                op = data.get('op')
                                t = data.get('t')
                                d = data.get('d')
                                
                                if op == 10:
                                    await ws.send_json({"op": 2, "d": {"token": TOKEN, "intents": 1, "properties": {"os": "linux", "browser": "Discord Android", "device": "Android"}, "guild_subscriptions": False, "large_threshold": 0}})
                                    
                                    if heartbeat_task:
                                        heartbeat_task.cancel()
                                    
                                    async def send_heartbeat():
                                        interval = d.get('heartbeat_interval', 41250) / 1000
                                        while True:
                                            try:
                                                if not ws.closed:
                                                    await ws.send_json({"op": 1, "d": None})
                                                await asyncio.sleep(interval)
                                            except:
                                                break
                                    
                                    heartbeat_task = asyncio.create_task(send_heartbeat())
                                
                                elif op == 0:
                                    if t == "READY":
                                        if d and 'guilds' in d:
                                            for guild in d['guilds']:
                                                if 'vanity_url_code' in guild and guild['vanity_url_code']:
                                                    guilds[guild['id']] = guild['vanity_url_code']
                                    
                                    elif t == "GUILD_UPDATE":
                                        guild_id = d.get('guild_id')
                                        new_vanity = d.get('vanity_url_code')
                                        
                                        if guild_id in guilds:
                                            old_vanity = guilds[guild_id]
                                            if old_vanity != new_vanity:
                                                # Blocking olmadan hemen başlat
                                                asyncio.create_task(extreme_snipe(old_vanity))
                                                
                                                if new_vanity:
                                                    guilds[guild_id] = new_vanity
                                                else:
                                                    del guilds[guild_id]
                            except:
                                pass
                        
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                    
                    if heartbeat_task:
                        heartbeat_task.cancel()
        except:
            pass
        
        await asyncio.sleep(2)

async def main():
    load_mfa_token()
    init_curl_pool()  # Curl pool'u başlat
    mfa_task = asyncio.create_task(periodic_mfa_loader())
    
    try:
        await websocket_handler()
    except:
        pass
    finally:
        mfa_task.cancel()
        executor.shutdown(wait=False)
        # Curl nesnelerini temizle
        for curl in curl_pool:
            curl.close()

if __name__ == "__main__":
    asyncio.run(main())
