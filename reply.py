"""Type the farmer's text; HerdX answers via SMS.

  python reply.py "B 22"
  python reply.py "M 18" --dry-run
  python reply.py                # interactive: keep typing replies, blank line to quit
"""
import argparse

from messages import FARM_FILE, handle_reply, load_json, load_table, save_farm
from sms import log_in, send


def respond(text, dry=False):
    farm, table = load_json(FARM_FILE), load_table()
    log_in(text)
    print(f"Farmer: {text}")
    answer = handle_reply(text, farm, table)
    save_farm(farm)
    send(answer, dry=dry)
    return answer


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.text:
        respond(a.text, a.dry_run)
    else:
        while (t := input("Farmer> ").strip()):
            respond(t, a.dry_run)
