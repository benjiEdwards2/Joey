# JY-324 "Goodnight" button: shut the system down for the night with one press

Status: options (B. 2026-11-05 "NAS services too": TV + Joey NAS containers, back by schedule; B. 2026-11-05: "I would be keen to also begin working on how to shut down the system with a button press at night.")
Size: TBC (S if it is only the TV app + TV off; M if the NAS services or the household devices are in it)
Live risk: TBC (anything that stops the NAS containers or the NAS itself is live risk)
Area: TBC (`hub/tv_app.py` / TV remote key, a Home button on desktop/phone, deploy scripts on the NAS)
Options page: yes, once the questions below are answered

## Questions for B.
1. What is "the system"? (a) the TV + Joey TV app only; (b) the Joey containers on the NAS (hub, downloaders, Jellyfin); (c) the NAS itself (power off, wake in the morning); (d) several household devices (TV, lights, speakers).
2. Where is the button? On the TV remote / TV app, on the phone Home page, on the desktop Home, or all of them?
3. What should still run overnight? Downloads, backups, the daily GitHub backup task at 17:00 is before bed; anything else that must not stop?
4. Morning: does it come back by itself (schedule, Wake-on-LAN) or on a button press too?
5. Guests/friends: owner-only button, or anyone on the TV?

## Build / Acceptance criteria
After the answers and an options page.
