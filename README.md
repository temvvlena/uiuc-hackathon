# HerdX — local demo (Oogii's build)

Python 3, runs on the Mac. No AWS, no dashboard, no database (`farm.json` holds the demo farm).

## Setup (once)
```bash
cd herdx
pip3 install pandas openpyxl requests matplotlib
cp .env.example .env        # set SMS_BACKEND=messages and FARMER_PHONE (see below)
```

## Run order
```bash
python3 loss_table.py "<dataset folder>"   # -> loss_table.json (already built; rerun only if needed)
python3 forecast.py                        # live 7-day forecast for Savar -> THI bands (check it works)
python3 forecast.py --save-demo-week       # fetch a hot July 2025 Savar week -> data/demo_weather.json
python3 charts.py                          # -> charts/*.png (first run fetches 10 yrs x 6 places, cached in data/)

python3 demo.py --demo-weather --dry-run --auto   # rehearse: prints every SMS, sends nothing
python3 demo.py --demo-weather --listen           # the real take: Enter between steps, reply from the farmer phone
```
**Alerts: at most one text per day**, sent in the morning, only when the day's mean heat index is >=79
(hot days + near-hot warm days). It gives the worst 4 hours, the day's litres and money at stake, what to do,
and asks for the 5 PM breath count. No weekly or day-before texts.
`python3 send_today.py [--demo-weather --day N] [--phone +1...] [--dry-run]` = the morning run a scheduler would do.

Other entry points:
`python3 reply.py "B 22"` (or no argument for an interactive prompt), `python3 listen.py` (answer real replies).

## Sign-up by text (any country)
`python3 listen.py` answers texts from the numbers in `HERDX_PHONES` (comma-separated in `.env`; default
`FARMER_PHONE`). From an allowed phone, text `JOIN` -> place (looked up worldwide, confirmed back) -> `YES` ->
herd `L0 H2 X1` (L local, H half-bred, X high-bred, U not sure) -> best milker `L/H/X` -> milk price (or `SKIP`).
HerdX then sends this week's forecast for that place right away. `STOP` leaves; `JOIN` restarts.
Each farm is saved as `farms/<number>.json`; the phone number is the identity.
`python3 onboard.py --list` shows farms; `python3 onboard.py --reset +1...` forgets one (to record the sign-up again,
or to put FARMER_PHONE back on the demo farm). `python3 send_today.py --phone +1...` sends a joined farm today's text (if today is hot).
`demo.py` always uses the demo farm (`farm.json`), whatever the phone has joined.

## Explore other places / weeks / herds
`python3 try.py --list` shows named places. Examples:
`python3 try.py --place rangpur --date 2025-05-10`, `python3 try.py --lat 23.0 --lon 89.2 --herd 3,1,0 --price 45`.
Live forecast if no `--date`. Prints only; add `--send` to text the farmer phone. Doesn't change the demo farm.

## Real SMS via your Mac's Messages app (Twilio trial can't send custom text)
1. **Your iPhone** (the sender): Settings > Apps > Messages > Text Message Forwarding > turn on this Mac.
   Messages on the Mac must be signed in to the same Apple ID.
2. **Farmer iPhone** (second phone): turn **iMessage off** (Settings > Apps > Messages) so both directions are
   real green-bubble SMS. Leave it on if you don't mind blue bubbles.
3. `.env`: `SMS_BACKEND=messages`, `FARMER_PHONE=+1...` (the farmer phone), `MESSAGES_SERVICE=sms`.
4. Test: `python3 reply.py HELP` -> the farmer phone should get the help text. The first run asks to let
   Terminal control Messages: allow it.
5. Real replies: give **Full Disk Access** to the app you run Python in (System Settings > Privacy & Security >
   Full Disk Access), restart it, then `python3 listen.py --once` and text `HELP` from the farmer phone.
6. Record: `python3 demo.py --demo-weather --listen` -> at each reply step, type `B 22` / `M 18` on the farmer phone.

If step 4 fails with "No SMS account", set `MESSAGES_SERVICE=imessage` (works, but blue bubbles = iMessage, not SMS).

## What demo.py does
1. Resets `farm.json` from `farm_demo.json`: Savar, 4 cows (Lali + Moni high-bred, Shada + Kali half-bred),
   best cow = Lali with two cool-day normal counts already stored (15, 16 per 30 s = 31 bpm).
2. Prints the week: which days get a text (heat index >=79) and which stay silent.
3. Sends the first hot day's morning text (worst hours, litres + taka, what to do, 5 PM breath count).
4. Farmer replies `B 22` (= 44 bpm, +13 over normal -> HIGH), then `M 18` -> confirmed and stored.

## Reply keywords
`B 22` breath count (30 s) · `B 22 20 21` several cows (after `MORE`) · `M 18` herd milk today · `MORE` · `HELP`

## Guardrails (implemented)
THI <75 → no alert · daily mean >85 → "at least … hotter than the study saw" · unknown cow type → range across all groups ·
count outside 10–40 → recount · multi-cow counts >5 apart → recount · milk outside 0–30 L/cow → ask again ·
every reply confirms the value back · forecast API fails → send nothing.

## Honesty notes for the video
- With `--demo-weather`, the week is real Open-Meteo history from July 2025 replayed as "this week" — say so.
- The sentinel's baseline is pre-seeded in `farm_demo.json` (in real use HerdX asks on two cool days).
- Charts a/b use the dataset; chart c uses Open-Meteo ERA5 history. "Weather data by Open-Meteo.com".
