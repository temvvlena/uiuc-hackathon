"""Reproducible video demo: Savar farm, 4 cows (2 half-bred + 2 high-bred, best cow = Lali, high-bred).

  python demo.py --demo-weather --listen           # the take: farmer replies from the second phone
  python demo.py --demo-weather --dry-run --auto   # rehearse without sending / pausing
  python demo.py --demo-weather --day 4            # pick which day of the week is "this morning"

Steps (Enter between them while recording):
  1. reset farm.json from farm_demo.json (Lali has 2 cool-day normal counts: 15, 16)
  2. week table: which days get a text (heat index >= 79) and which stay silent
  3. the hot morning's text (alert + actions + breath check-in request)
  4. farmer replies with Lali's count (default "B 22") -> HerdX: HIGH / not high
  5. farmer replies milk today (default "M 18") -> saved
"""
import argparse
import shutil
import sys

from forecast import WeatherError, get_week
from messages import FARM_FILE, load_json, load_table, save_farm
from reply import respond
from send_today import behind_the_scenes, todays_text
from sms import send

DEMO_FARM = FARM_FILE.replace("farm.json", "farm_demo.json")


def pause(auto, label):
    print(f"\n===== {label} =====")
    if not auto:
        input("[Enter] to continue ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-weather", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto", action="store_true", help="no pauses; use default replies")
    ap.add_argument("--listen", action="store_true",
                    help="wait for the farmer's real text replies (Messages backend)")
    ap.add_argument("--day", type=int, help="day index for 'this morning' (default: first hot day)")
    a = ap.parse_args()

    shutil.copy(DEMO_FARM, FARM_FILE)
    farm, table = load_json(FARM_FILE), load_table()
    try:
        week, note = get_week(farm, demo=a.demo_weather)
    except WeatherError as e:
        print(f"{e}\nGuardrail: no forecast -> nothing sent.")
        return 1
    days = list(week.itertuples())
    idx = a.day if a.day is not None else next((i for i, r in enumerate(days) if r.band == "T2"), None)
    if idx is None:
        print("No hot (>=80) day this week. Try --demo-weather, or pick a day with --day.")
        return 0

    pause(a.auto, "The week behind the scenes (one text per hot morning, silence otherwise)")
    behind_the_scenes(week, farm, table, note, idx)

    pause(a.auto, f"{days[idx].date.strftime('%A')} morning: the day's text")
    text, pending = todays_text(week, farm, table, idx)
    if not text:
        print("That day is below heat index 79 -> no text. Pick another --day.")
        return 0
    farm["pending_checkin"] = pending
    save_farm(farm)
    send(text, dry=a.dry_run)

    for label, default in [("5 PM: farmer's breath count", "B 22"), ("Evening: farmer's milk", "M 18")]:
        print(f"\n===== {label} =====")
        if a.listen:
            from listen import wait_for_reply
            reply_text = wait_for_reply()
            if reply_text is None:
                print("No reply within 10 minutes - stopping.")
                return 1
        else:
            reply_text = default if a.auto else (input(f"Farmer types [{default}]: ").strip() or default)
        respond(reply_text, dry=a.dry_run)
    print("\nDemo done. Log: outbox.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
