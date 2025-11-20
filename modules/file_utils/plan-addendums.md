```
Filter: *                                                                   Path: . | Sort: created (desc) | Items: 153                                 2025-11-13 22:40:29  ▼ kenra_sunderland/                      1.85 GiB (6k) 2025-11-13 22:40:29    ▶ _tmp/                                              2025-11-13 22:40:44      - Young And Beautiful 5 1080p.mp4.part  493.98 KiB 2025-11-13 22:40:28  ▼ ariana_marie/                          1.60 GiB (6k) 2025-11-13 22:40:28    ▼ _tmp/                                        [...] 2025-11-13 22:40:33      ▶ 220886/                                          2025-11-13 22:40:43      - Stepsibling Secrets 1080p.mp4.part    461.32 KiB 2025-11-09 05:26:19  ▶ aika_javhd/                                97.92 MiB

```
As shown above a 's' (scan all was run).. however, for soms reason some folders when expanxed no longer sbow their xontribution toward the toral size.. tbis should not happen. Once a scan js run and finished, all sizss sboukd bs tracked fkr tje remainder of session

Additionally, i think kt wlukd be useful to have a seco d column dedicaged to the filecounts residi g sithkn the item at eacb row..

Additionally, im not sude why this happens but somstimes after a scan and a collapse the item shows a series of sub items, where the subitem witj blank text has a huge portion

```
Filter: *                                                                   Path: . | Sort: size (desc) | Items: 165                                    2025-10-17 09:38:08  ▼ britt_blair/                         99.48 GiB (76k) 2025-10-17 09:38:08    ▶ _tmp/                                              2025-10-28 20:05:49      - Sis Swap 4 1080p.mp4.part            1020.77 KiB 2025-10-26 05:27:32      - One BBC Isn't Enough 1440p.mp4.part   765.17 KiB 2025-10-26 02:05:59      - Ignite 9 1440p.mp4.part               736.61 KiB 2025-10-21 17:32:26      - Taking My Stepdaughter's Ass 1440...  614.33 KiB 2025-10-21 18:10:45      - My Husband's Best Friend 4 1080p....  367.74 KiB 2025-10-28 22:21:19      - Blacked Raw V85 1440p.mp4.part             536 B 2025-10-17 12:30:07  ▶ jenna_reid/                                85.56 GiB 2025-10-04 14:40:19  ▶ liya_silver/                               72.71 GiB 2025-10-04 14:40:19  ▶ savannah_sixx/                             60.54 GiB 2025-10-04 14:40:19  ▶ eliza_ibarra/                              60.47 GiB 
```

Pressing enter on the foldee without the sizes does nothing other rhanopen the folder normally. I think we should have a mode where once sizes have been calcukated and are being displaysd, if an instance occurs (say where we open a folder with unknown subfolder sizes) the unknown sizes are auto calcjlated and dksplayed. Secondly, we sbould bave a button we can press to calculate only the highlighted values...and alsk have a button to.calculate all values.

We shluld have a button to collapse all open folders and subfolders easily as well. Additionally, we sbould have tbe ability to select mt
ultiple rows easily, eitber by starting a dragged selectiom, mvoing the end selector bar whe the placed selector bar stays in place. Also shpuld be able to select out N lines up pr dowm usomg vim-like commands

Ultimatly with tje more advanced filtsring and selection+exclusion abilities, we ahould also gain a more defailed and ingeractive interactive page... it should give us the ability to, for example, find the top 50 files of a extension and od matching a patfern, and then allow us to scroll tjrough this list of.files, eventually aallowing the application of operations to our lists, such as deleting the files found in soms custom list of list we've made

we should also gain thr ability to save and load lists and list->setopsrations (allow for  dry running of saved lists as wsll as chsnging of inout list parameters.)

We shouls be able to get stats and summaries regarding the files tskong ip the most space, the mosr numbers, the nbers and sizes bynextension types, etc

Opening all folders at once doesnt appear tk work, nor dkes rhe reverse. we sbluld be able tk easily open all folders to both a max depth wktb lne command, i.e. open all folders to depth kf 2. we shojld.jusy aseaskly beable to open all folders an additional amoumt lf delth (default 1). Also closing up open hierarchkves shluld be just as easy.

---

Progress 2025-11-20:
- Added always-visible item counts alongside calculated sizes.
- Added hotkeys: `r` to calculate the highlighted folder, `A` to calculate all visible folders, `U` to collapse all expansions.
- Retained `S` for full-tree size scan; footer updated to reflect the new controls.
