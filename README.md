# Mirage
Robots and self-driving cars need training data. SynSplatt synthesize 3D world-model training data covering hard-to-capture scenes - like driving in a hailstorm.

 - https://github.com/kyan-yang/Mirage
 - Try it at vercel
 - demo video

Created at TreeHacks 2026 by Shrey Birmiwal, Kyan Yang, Kevin Thomas, Adi Prasad

## Motivation

 - The future of AI-like robots and self-driving cars requires lots and lots of data.
 - Current datasets are extensive, but they cover common senarios, like driving in a sunny or cold day.
 - They **overrepresent positive cases and underrepresent edge cases** and failure cases, where things could actually go wrong.
 - This leads us to believe that simulations of world models will be key to simulating edge cases, like driving when a tree hits the ground, to train more robust and safe models.
 - Conviction is furthered by Waymo beginning similar research, [seen here](https://x.com/Waymo/status/2019804616746029508?s=20)

## What did we do?

 - Users will create prompts, such as **"Generate a road that had a tree break and fall down on"**, a unique scenario that would be unlikely to be present in current datasets, but very valid and important to train a model on.
 - An LLM hosted on Google Cloud will expand the user prompt
 - Veo3 model hosted on Google Cloud will generate a video of the simulated road
 - Modal hosting multiple h100 GPUs will run an open source world model / gaussian splatting algorithm to create a 3d representation of this world

## Future work (half completed at hackathon)

 - Physics + simulations in 3D generated space
 - Segmentation of objects in 3d representation space (enabling the moving of objects in the space, identification, and training)
