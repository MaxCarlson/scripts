---
plan_index: 0001
origin: user
status: superseded
source_file: 99_xx_percent_stuck_plan.md
---

Same old 99.90% stuck issue:
```
>[05] | upperfloor2.txt                          | URL 1/1      | Elapsed 00:05:04 | 99.90%   | 44.55MiB/s   | ETA 00:00:00 | Dom pornhits.com     | 927.84MiB  | 928.77MiB
  >[Y]  [======================================================================================================================================================================
 [06] | upperfloor2.txt                          | URL 1/1      | Elapsed 00:01:48 | 99.60%   | 42.68MiB/s   | ETA 00:00:00 | Dom pornhits.com     | 978.98MiB  | 982.91MiB
   [Y]  [======================================================================================================================================================================
[Simulating…] checking for existing file at destination
   [Y]  [.........................................................................................................................................................................]
 [08] | yuki_rino.txt                            | URL 1/1      | Elapsed 00:00:04 | ?%       | ?/s          | ETA ?        | Dom eporner.com      |            |
   [Y]  [.........................................................................................................................................................................]
----------------------------------------------------------------------------------------------------
Program Log [05]
                        url: https://pv.pornhits.com/v1/preview/55295.mp4
[13:25:45][00:00:11.164] FALLBACK_RESULT attempt 4/5  method=static_html  FAILED (rc=1)
[13:25:45][00:00:11.165] ATTEMPT_5_FAIL   static_html direct candidate 4/5  (exit code 1)
[13:25:45][00:00:11.165] ATTEMPT_6_START  static_html direct candidate 5/5
[13:25:45][00:00:11.166] FALLBACK_TRY    attempt 5/5  method=static_html  kind=direct
                        url: https://pv.pornhits.com/v1/preview/57131.mp4
[13:25:46][00:00:12.015] FALLBACK_RESULT attempt 5/5  method=static_html  FAILED (rc=1)
[13:25:46][00:00:12.016] ATTEMPT_6_FAIL   static_html direct candidate 5/5  (exit code 1)
[13:25:46][00:00:12.017] FALLBACK_START  method=browser_network
[13:26:06][00:00:31.908] ATTEMPT_7_START  browser_network hls candidate 1/5
[13:26:06][00:00:31.909] FALLBACK_TRY    attempt 1/5  method=browser_network  kind=hls
                        url: https://ahcdn.pornhits.com/key=Nvh2fDmuocPTLLdtFhAd8w,end=1778444752,limit=3/media=hlsA/referer=none…
[13:26:07][00:10:36.433] DOWNLOAD_START  [1/1] https://www.pornhits.com/video/32987/gorgeous-kink-photographer-gets-curious/
[13:26:22][00:10:51.438] PROGRESS        66.1% 641.10MiB/969.89MiB @ 43.34MiB/s ETA 00:00:08
Keys: w=watcher, u=url stats, d=downloads, Up/Down=select worker, P=toggle selected, p=pause/unpause all, x=controlled quit, h=toggle status, q=quit, v=cycle verbose, digit=prompt
worker number

And other verbose output for same worker:
----------------------------------------------------------------------------------------------------
Verbose NDJSON [05]
{"event": "progress", "percent": 99.59999999384468, "total": 974766735, "downloaded": 970867668, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.59999998235514, "total": 974787707, "downloaded": 970888556, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.49999999743672, "total": 975311995, "downloaded": 970435435, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.60000002379289, "total": 975081308, "downloaded": 971180983, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.59999996883217, "total": 975364424, "downloaded": 971462966, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.60000004182828, "total": 975416852, "downloaded": 971515185, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.60000000491786, "total": 976035512, "downloaded": 972131370, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.59999998770576, "total": 976066970, "downloaded": 972162702, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.49999997133561, "total": 976821944, "downloaded": 971937834, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.50000001586405, "total": 977052631, "downloaded": 972167368, "speed_bps": 46787461.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.79999996656616, "total": 975060337, "downloaded": 973110216, "speed_bps": 46714061.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.69999995776664, "total": 975532196, "downloaded": 972605599, "speed_bps": 46714061.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.89999997822568, "total": 973623788, "downloaded": 972650164, "speed_bps": 46714061.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
{"event": "progress", "percent": 99.89999999301766, "total": 973885932, "downloaded": 972912046, "speed_bps": 46714061.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url"
Keys: w=watcher, u=url stats, d=downloads, Up/Down=select worker, P=toggle selected, p=pause/unpause all, x=controlled quit, h=toggle status, q=quit, v=cycle verbose, digit=prompt
worker number
```
Also weirdly appeared at 99.60%
```
>[06] | upperfloor2.txt                          | URL 1/1      | Elapsed 00:02:45 | 99.60%   | 42.68MiB/s   | ETA 00:00:00 | Dom pornhits.com     | 978.98MiB  | 982.91MiB
  >[Y]  [======================================================================================================================================================================
[Fallback:browser_network] Trying candidate 1/5 (direct)…
   [Y]  [.........................................................................................................................................................................]
 [08] | freya_mayer.txt                          | URL 1/1      | Elapsed 00:00:04 | ?%       | ?/s          | ETA ?        | Dom hqporner.com     |            |
   [Y]  [.........................................................................................................................................................................]
----------------------------------------------------------------------------------------------------
Verbose NDJSON [06]
{"event": "progress", "percent": 98.30000004189556, "total": 1035909202, "downloaded": 1018298746, "speed_bps": 45413827.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.60000000909366, "total": 1033686221, "downloaded": 1019214614, "speed_bps": 45413827.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.69999996296693, "total": 1034210509, "downloaded": 1020765772, "speed_bps": 45413827.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.59999999942045, "total": 1035269571, "downloaded": 1020775797, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.59999999325323, "total": 1037534495, "downloaded": 1023009012, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.59999995354231, "total": 1037503037, "downloaded": 1022977994, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.69999999932462, "total": 1036454461, "downloaded": 1022980553, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 98.70000003916645, "total": 1036601262, "downloaded": 1023125446, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 99.20000000465198, "total": 1031819756, "downloaded": 1023565198, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 99.1000000467815, "total": 1032459387, "downloaded": 1023167253, "speed_bps": 45308969.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url
{"event": "progress", "percent": 99.50000003105546, "total": 1030414664, "downloaded": 1025262591, "speed_bps": 44983910.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 99.29999995175194, "total": 1032165786, "downloaded": 1024940625, "speed_bps": 44983910.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 99.80000002507367, "total": 1028967629, "downloaded": 1026909694, "speed_bps": 44753224.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "ur
{"event": "progress", "percent": 99.6000000333768, "total": 1030655836, "downloaded": 1026533213, "speed_bps": 44753224.0, "eta_s": 0, "downloader": "yt-dlp", "url_index": 1, "url
Keys: w=watcher, u=url stats, d=downloads, Up/Down=select worker, P=toggle selected, p=pause/unpause all, x=controlled quit, h=toggle status, q=quit, v=cycle verbose, digit=prompt
worker number

and other verbose output for same 99.60% sstuck worker:

>[06] | upperfloor2.txt                          | URL 1/1      | Elapsed 00:03:22 | 99.60%   | 42.68MiB/s   | ETA 00:00:00 | Dom pornhits.com     | 978.98MiB  | 982.91MiB
  >[Y]  [======================================================================================================================================================================
[Fallback:static_html] Trying candidate 3/5 (direct)…
   [Y]  [.........................................................................................................................................................................]
 [08] | freya_mayer.txt                          | URL 1/1      | Elapsed 00:00:41 | ?%       | ?/s          | ETA ?        | Dom hqporner.com     |            |
   [Y]  [.........................................................................................................................................................................]
----------------------------------------------------------------------------------------------------
Program Log [06]
                        url: https://pv.pornhits.com/v1/preview/30102.mp4
[13:29:02][00:00:11.954] FALLBACK_RESULT attempt 5/5  method=static_html  FAILED (rc=1)
[13:29:02][00:00:11.955] ATTEMPT_6_FAIL   static_html direct candidate 5/5  (exit code 1)
[13:29:02][00:00:11.955] FALLBACK_START  method=browser_network
[13:29:22][00:00:31.212] ATTEMPT_7_START  browser_network hls candidate 1/5
[13:29:22][00:00:31.212] FALLBACK_TRY    attempt 1/5  method=browser_network  kind=hls
                        url: https://ahcdn.pornhits.com/key=XDV6cJUXfBuytcHfZXwzew,end=1778444947,limit=3/media=hlsA/referer=none…
[13:29:23][00:00:32.276] FALLBACK_RESULT attempt 1/5  method=browser_network  FAILED (rc=1)
[13:29:23][00:00:32.281] ATTEMPT_7_FAIL   browser_network hls candidate 1/5  (exit code 1)
[13:29:23][00:00:32.281] ATTEMPT_8_START  browser_network hls candidate 2/5
[13:29:23][00:00:32.283] FALLBACK_TRY    attempt 2/5  method=browser_network  kind=hls
                        url: https://ahcdn.pornhits.com/key=Pb3xy+gCT4Q6qRLFSSUm5Q,end=1778444947,limit=3/media=hlsA/referer=none…
[13:29:24][00:13:53.121] DOWNLOAD_START  [1/1] https://www.pornhits.com/video/78607/banging-gia/
[13:29:39][00:14:08.123] PROGRESS        72.8% 704.75MiB/968.06MiB @ 48.47MiB/s ETA 00:00:06
Keys: w=watcher, u=url stats, d=downloads, Up/Down=select worker, P=toggle selected, p=pause/unpause all, x=controlled quit, h=toggle status, q=quit, v=cycle verbose, digit=prompt
worker number
```

Now this is somewhat interesting because I always thought this bug was from aebndl starting a partially downloaded file... however we deleted all _tmp folders and all .partial files and this is from the first run so obviously this behavior doesn't come from that. Additionally this is the first time I see two numbers the download appears stuck at. I'm thinking this is some sort of issue with not changing the UI and logs and maybe the worker itself, or a lot of it's synchronized state, when the URL is being tested or has already been determined to be some way? Just speculation on my part...
