import torch
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer("all-MiniLM-L6-v2")

triggers = ["but the truth is", "the biggest mistake", "went from"]
sentences = [
    "amazon famously lost money for a decade, but the truth is they were mapping networks.",
    "the biggest mistake people make is thinking they can do it alone.",
    "i went from being broke to a millionaire in 5 years.",
    "but they were mapping networks.",
    "so the reality of the situation is quite different.",
    "i changed my life completely."
]

t_emb = model.encode(triggers, convert_to_tensor=True)
s_emb = model.encode(sentences, convert_to_tensor=True)

sims = util.cos_sim(s_emb, t_emb)

for i, s in enumerate(sentences):
    print(f"\nSentence: '{s}'")
    for j, t in enumerate(triggers):
        print(f"  vs '{t}': {sims[i][j].item():.3f}")

