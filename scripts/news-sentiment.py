"""Classify sourced headlines locally on a GitHub CPU runner; no paid API."""
import json
import sys
MODEL = 'mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis'
with open(sys.argv[1], encoding='utf-8') as handle:
    data = json.load(handle)
headlines = [h for company in data['companies'] for h in company['headlines']]
data['model'] = {'name': MODEL, 'modelCard': 'https://huggingface.co/' + MODEL}
try:
    if headlines:
        import torch
        from transformers import pipeline
        torch.set_num_threads(2)
        classifier = pipeline('text-classification', model=MODEL, device=-1, model_kwargs={'use_safetensors': True}, trust_remote_code=False)
        labels = {value.lower() for value in classifier.model.config.id2label.values()}
        if labels != {'positive', 'negative', 'neutral'}:
            raise ValueError('Model has unexpected sentiment labels')
        scores = classifier([h['title'] for h in headlines], top_k=None, truncation=True, max_length=256, batch_size=16)
        for headline, result in zip(headlines, scores):
            headline['sentiment'] = {r['label'].lower(): float(r['score']) for r in result}
        data['model']['revision'] = classifier.model.config._commit_hash
    data['modelState'] = 'available' if headlines else 'no-headlines'
except Exception as error:
    data['modelState'] = 'unavailable'
    data['modelError'] = str(error)[:500]
    for headline in headlines:
        headline.pop('sentiment', None)
    print('News sentiment unavailable: ' + str(error)[:300], file=sys.stderr)
with open(sys.argv[2], 'w', encoding='utf-8') as handle:
    json.dump(data, handle)
