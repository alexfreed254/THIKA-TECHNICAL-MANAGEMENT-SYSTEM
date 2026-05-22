# TODO

## Auth unified login rollout
- [x] Locate unified login route + auth blueprint wiring.
- [x] Verify `/auth/login` POST handling supports:
  - [x] Trainee/admission login (admission_number + password → lookup students → Supabase sign-in)
  - [x] Staff/email login (email + password → Supabase sign-in)
- [x] Ensure role routing after login works (super_admin/dept_admin/trainer/student).
- [x] Update login template to show THIKA TECHNICAL MANAGEMENT SYSTEM header and two-tab UI.
- [x] Ensure template posts to `/auth/login` with `login_type` + correct fields.
- [x] Confirm active tab persistence using `active_tab` variable.
- [x] Review/avoid string replacement mismatches during incremental template edits.

## Follow-up checks (manual/test)
- [ ] Run server and test:
  - [ ] Staff login flow with valid email/password
  - [ ] Trainee login flow with valid admission_number/password
  - [ ] Disabled profile behavior
  - [ ] Missing `user_profiles` self-healing
- [ ] If any old pages still link to removed routes, update redirects/links.

