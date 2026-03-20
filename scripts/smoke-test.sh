#!/bin/bash

uv run s-peach say "Say it out loud!" --model kitten-nano --voice Rosie
sleep 0.5
uv run s-peach say "Say it out loud!" --model kitten-micro --voice Rosie
sleep 0.5
uv run s-peach say "Say it out loud!" --model kitten-mini --voice Rosie
sleep 0.5
uv run s-peach say "Say it out loud!" --model kokoro --voice Nicole
sleep 0.5
uv run s-peach say "Say it out loud!" --model chatterbox --voice Bea
sleep 0.5
uv run s-peach say "Say it out loud!" --model chatterbox-turbo --voice Bea
sleep 0.5
uv run s-peach say "Say it out loud!" --model chatterbox-multi --voice Bea --lang fr
