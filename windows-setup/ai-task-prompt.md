# Directions for hosting this setup in windows for my uncle who just bought a geekom (note he will nto be  gettin external graphics  though))

In this set up with will include an explajnatioan of all aspect of this set up, the configuration and softwarer installation. ill note herer that he already changed his video ram mto 96gb.

you wiklll end up putting the windows instructionms and configuration in folder windows-setup

## give an overview of what THios guide is about
This is what its about:
1. confiuration and set up of very useful local LLMs
2. Configuration of bifrost gateway so all trafic goes througn one place allowws a degree of cobtrol oi the communcxiation. the main reason i put it there is to alloow me to speak top anny of my agents directlky while styill having the option to speak to a 'model' which is actyually orchestration which will desig weork to the visual agent, coding tasks to the coder and general work top the generalikst

## Download and install required software
Includee a list of softwaere to instal on window:

Examples:
- Docker Desktop
- lamma.cpp
- pythnon
- a R|AG db (i suggest dockerised)
- nyou might want to ahav esoftware installed that will make tooling for the agents,easier
- if there is any specific geekom strrix halo software out there to get the most out of your hardwarer
- clinie
- opencode
- discords (to chat to Heres and Nanoclaw)

## Model list, where to download, how to install
1. MiniMax-M2.7 UD-Q3_K_S (87 GB MoE, 62 layers / 256 experts) — fits FULLY in 96 GB VRAM → all layers on GPU, NO --n-cpu-moe. Verified ~18 tok/s on the iGPU (GPU busy 60-99%). This is the usable heavy reasoner on this box.
2. Llama-3.2-11B-Vision — OCR / documents / diagrams. 
3.  Qwen 2.5 72B (~42GB VRAM) — The heavyweight reasoner "Main Guy"
4. Gemma 4 31B BF16 (~62 GB VRAM) — Excellent speed and quality balance
5. Qwen 3.6 27B — Faster MTP architecture, incredibly fast coder
6. Qwen2.5-VL 7B (vision) — OCR / documents / diagrams / multimodal math
7. Gemma-3 12B (vision) — general VQA / chart understanding / captioning

Pledase provide exact llama.cpp configuration  so the will be paninless and woring out the gates
## The bifrost gateway and prompt orchedstration
prompt a dormant agent will try the whole thing to loaded into RAM. so to not exceed memore usage i created a fast and max more (whch swaps out the respective coder and hte respect viswi0on models for the same model just with more or less optimizations.

So the bifront gatway sites beween ther the llm consuer and the llm

I haave configurated the gateway to be able to sended a propmpt the agent msot sioted fpr whatever ios   being asked. and yes the llms can analyse impage, evn the local opnes

## Setting up a nanoclaw 'general helper' and a self improing Hermes 'Daniels Work Specialis'
So Daniel (uncles njame)b is looking to get an agent to learn to work he is doing (essentually having a series of phyical documents, sreadsheetamnd a test
 have a reo which cointains my setup and configurationmm ofthhis machine. you can find this repo at /mnt/Shared/personal/agents

essentuall Daniel ius not a coder but denial is a bof and an engineer. his agents should speak to the ai model orchestrator (its makes sense, ieither that or opencodfe directly).

the documentation should briefly eexplain to daniel wha


## This tasks deliver
this is the mono repo- root:
