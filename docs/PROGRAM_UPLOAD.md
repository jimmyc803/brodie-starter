# Coach program uploads

Open `/coach/start` to create a private coach workspace and its first client. Save the resulting private coach link: it grants access to that coach's programs and clients. The shared demo coach remains view-only and links to this onboarding flow.

From the private Programs page, upload a PDF of up to 3 MB. The existing server pipeline stores it privately, uses the dedicated `GEMINI_PARSER_API_KEY` to parse it, and saves the complete program with its training days. Check the returned prescriptions against the original PDF before assigning a day. Parser failures remove the temporary PDF; uncertain database saves retain it and ask the coach to refresh before retrying.

Unsupported exercises are preserved with sets, reps and notes and labeled **No video tracking**. They are not included in the automated call. Mixed days run only their supported movements; days with no tracked movements remain saved but cannot be assigned to a video call. Discuss those exercises with the Brodie team before video support can be added.

The Exercise support review section creates a local text brief of unsupported exercises. Coaches can copy or download it to share with their Brodie contact. This does not create a ticket or send a message. Optionally configure `COACH_SUPPORT_BOOKING_URL` on the server with the team's HTTPS scheduling URL; only then will the page offer a booking link. Coaches complete scheduling on that external page. No booking is claimed by Brodie.
