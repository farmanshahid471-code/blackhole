PUT YOUR BACKGROUND MUSIC IN THIS FOLDER
========================================

Any audio files here are used automatically as the music bed under the
narration. Nothing else needs configuring - drop a file in and press build.

SUPPORTED FORMATS
    .mp3   .wav   .m4a   .ogg   .flac

HOW A TRACK IS CHOSEN  (config.yaml -> audio.music.mode)
    random      pick one at random every video          <- default
    first       always the first file, alphabetically
    filename    always the exact file named in
                audio.music.filename
    match_mood  ask the LLM which track suits the script
                (rename files like "tense_dark.mp3" and it
                 picks the best match for each video)

USEFUL TIP - NAME YOUR FILES BY MOOD
    calm_space_ambient.mp3       ancient_mystery.mp3
    tense_dark_drone.mp3         uplifting_orchestral.mp3
    With mode: match_mood the bot then chooses sensibly per topic.

WHERE TO GET FREE MUSIC THAT IS SAFE TO MONETISE
    YouTube Audio Library   https://studio.youtube.com  (Channel -> Audio Library)
    Free Music Archive      https://freemusicarchive.org  (check each licence)
    Pixabay Music           https://pixabay.com/music/
    Incompetech (Kevin MacLeod)  https://incompetech.com/music/

    -> Always check the licence. "CC BY" means you must credit the artist,
       usually in the description. "CC0" / public domain needs no credit.

IMPORTANT - THE BOT DOES NOT NEED A TRACK
    This folder is empty by default. Without music the video is simply 100%
    narration, which is what a lot of documentaries do anyway. Nothing breaks.

HOW THE MIXING WORKS  (all automatic, all configurable)
    1. your track is looped to cover the whole video
    2. it is faded in (1.5s) and out (3s) so it never starts or stops abruptly
    3. it is turned down to about -19 dB, well under the voice
    4. DUCKING: whenever the narrator speaks the music automatically dips,
       then swells back up in the pauses - the trick professional editors do
       by hand. Turn it off with  audio.music.ducking: false
    5. the narration is normalised to -16 LUFS (the YouTube standard) and the
       whole mix is limited so it can never clip or distort
