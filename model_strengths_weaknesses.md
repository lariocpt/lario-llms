# Installed Local Models: Strengths and Weaknesses

Based on your local configuration, you have three primary models installed on your machine. Here is a breakdown of what each one does best and where they might fall short.

## 1. Llama 3.3 (70B)
**Alias in config:** `llama3.3:70b`

### Strengths
*   **The Ultimate Generalist:** This is currently one of the best overall open-weights models in the world. It excels at complex reasoning, creative writing, and nuanced instruction following.
*   **Human-like Tone:** It feels incredibly natural to talk to and is fantastic for brainstorming, editing text, or acting as an all-purpose assistant.
*   **Versatility:** Capable of handling almost any task you throw at it (coding, math, logic, roleplay) at a very high level.

### Weaknesses
*   **Resource Heavy:** At 70 billion parameters, it is the heaviest model on your machine. It takes up a significant chunk of your memory and generates text slower than the others.
*   **Not Specialized:** While great at coding, it can sometimes be beaten on extremely complex programming algorithms by smaller, hyper-specialized models (like your Qwen Coder).

---

## 2. Qwen 2.5 Coder (32B)
**Alias in config:** `qwen2.5-coder:32b`

### Strengths
*   **World-Class Coding:** This model is hyper-trained specifically for software development. It frequently matches or beats much larger models in programming benchmarks.
*   **Fast & Efficient:** At 32 billion parameters, it is less than half the size of Llama 3.3. This means it will run blazingly fast on your machine while sipping memory.
*   **Logic and Math:** Excellent at breaking down complex logical puzzles, refactoring code, and debugging.

### Weaknesses
*   **Narrow Focus:** Because it was trained heavily on code, it is not the best choice for creative writing, general knowledge questions, or casual conversation.
*   **Refusal/Quirks:** It can sometimes struggle with non-technical instructions or occasionally default to its multi-lingual roots (Qwen is developed by Alibaba) if prompted ambiguously.

---

## 3. Llama 3.2 Vision (11B)
**Alias in config:** `llama3.2-vision:latest`

### Strengths
*   **Multimodal (Sight):** This is your only model that can "see." It is perfect for analyzing images, extracting text from screenshots, or describing visual charts and diagrams.
*   **Extremely Lightweight:** At only 11 billion parameters, this model takes almost no resources to run and generates responses almost instantly.

### Weaknesses
*   **Lower Reasoning Capability:** Because it is so small (11B), its pure textual logic, coding ability, and complex reasoning are significantly lower than the 32B and 70B models.
*   **Strictly for Vision:** You should almost entirely reserve this model for tasks that require analyzing an image. For pure text tasks, the other two models will vastly outperform it.

---

## 4. Ideogram 4 (9.3B)
**Execution Script:** `python3 generate_ideogram.py --prompt "..."`

### Strengths
*   **Best-in-Class Text Rendering:** Highly acclaimed for its ability to render legible, correct text, typography, and logo-like elements within generated images.
*   **Structured Layout Control:** Excellent at managing complex layouts, spatial placement, and structured visual compositions.
*   **Open Weights & Local Execution:** Runs completely offline and locally on your Strix Halo workstation.

### Weaknesses
*   **Licensing:** Released under the Ideogram Non-Commercial Model Agreement (requires commercial licensing for paid projects).
*   **Gated Weights:** Requires a Hugging Face account and access token (`HF_TOKEN`) to download from Hugging Face.
*   **Speed/Compute:** Requires more inference steps (typically ~30 steps) compared to Flux.1-schnell (~4 steps) to produce high-quality results.

---

## 5. Qwen 3 Coder Next
**Alias in config:** `qwen3-coder-next` / `qwen3-coder-next:latest`

### Strengths
*   **Next-Generation Coding:** The cutting-edge coding model built specifically for software engineering tasks, API integration, and agentic workflows.
*   **Excellent Context Window:** Handily processes massive code snippets, files, and multi-file codebases without losing context.
*   **Modern Language Syntax:** Highly optimized for modern frameworks, packages, and syntax across dozens of programming languages.

### Weaknesses
*   **Hardware Demand:** Slightly heavier compared to previous Qwen iterations, requiring more unified memory on Strix Halo when executing large agent runs.
*   **Domain Specialization:** Highly geared toward coding and technical logic, making it less ideal for general creative writing.

---

## 6. GLM 4.7 Flash
**Alias in config:** `glm-4.7-flash:bf16`

### Strengths
*   **High-Speed Inference:** Extremely fast response times and token generation speed, making it perfect for quick questions and dev iterations.
*   **Native BF16 Precision:** Uses `bfloat16` to deliver high reasoning accuracy with a relatively lightweight footprint.
*   **Strong Multilingual Support:** Highly proficient in both English and Chinese conversational contexts.

### Weaknesses
*   **Complex Logic Limitations:** While fast, its reasoning on multi-layered logical puzzles and extreme math can fall behind Llama 3.3 (70B) or Qwen 3 Coder Next.

---

## 7. Meditron (Medical)
**Alias in config:** `meditron:70b` / `meditron:latest`

### Strengths
*   **Clinical Knowledge:** Fine-tuned specifically on medical texts, QA datasets, and clinical guidelines. Excels at clinical decision support and medical reasoning.
*   **Medical Terminology:** Possesses deep understanding of pharmacology, anatomy, and clinical concepts.

### Weaknesses
*   **Highly Specialized:** Absolutely NOT meant for coding, general reasoning, or creative tasks.
*   **Computationally Expensive (70B):** At 70 billion parameters, the larger variant requires significant memory resources and is slow to generate responses.

---

### Summary for Daily Use:
*   Use **Llama 3.3 (70B)** for general questions, deep reasoning, and complex conversational tasks.
*   Use **Qwen 2.5 Coder (32B)** or **Qwen 3 Coder Next** when you are deep into OpenCode or Palot and need fast, accurate programming assistance.
*   Use **Llama 3.2 Vision (11B)** whenever you need to upload an image or screenshot for analysis.
*   Use **Ideogram 4 (9.3B)** for high-fidelity text-to-image design work, especially when accurate spelling or text layouts are required.
*   Use **GLM 4.7 Flash** when you need blazingly fast general text generation.
*   Use **Meditron (70B)** specifically for medical-domain queries and clinical decision guidance.

