# Kite Sessions to Strava

## Overview

I'm an avid [kitesurfer](https://www.ikointl.com/blog/complete-beginners-guide-know-everything-about-kitesurfing). I use apps like [Woo](https://woosports.com), [Surfr](https://www.thesurfr.app/), and [Hoolan](https://www.hoolan.app/) to record my kitesurfing sessions.
They provide awesome, kite-specific stats that are fun to review per session.

The trouble is, that's not the only sport that I do, and for everything else, I record my sessions with [Strava](https://strava.com).

Strava has [does have kiteboarding](https://support.strava.com/hc/en-us/articles/216919407-Supported-Sport-Types-on-Strava) as a session type, but it doesn't do any of the cool analytics that I care about as a kiter. 
But Strava is also where I keep track of my overall fitness, and I want to generally have the sessions represented there.

Now, I can manually export [GPX files](https://www.topografix.com/gpx.asp) from the Kiteboarding apps. And then, of course, I can go to Strava and manually upload that GPX, and fill in all the info.
But I've got *hundreds* of sessions. So unless you already started by manually uploading each session everytime you kite, that's hours of work. 

That's where this project comes in!

This project is a [Python](https://www.python.org/) [container](www.docker.com/resources/what-container/) that accepts a [file path](https://www.codecademy.com/resources/docs/general/file-paths) to multiple GPX files, and automatically gets their information, and cleanly uploads to Strava. 
