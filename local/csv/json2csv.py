import pandas as pd
import json

if __name__ == "__main__": 
    with open('responses.json', 'r', encoding='utf-8') as file:
        data = json.load(file)

    # Normalize JSON data without expanding lists
    cols = ['participant_uid', 'query_id', 'query_order', 
            'reading_time', 'decision_time', 'N', 'word_selected', 'label',
            'words_not_selected'] 
    rows = []
    for _, participant_responses in data['participant_responses'].items():
        for participant_response in participant_responses:
            participant_uid = participant_response['participant_uid']
            query = participant_response['text_query']['primary_description']
            query_id, query_order = query.split(' ')[0], query.split(' ')[1:]
            decision_time = participant_response['decision_time']
            reading_time = participant_response['reading_time']
            N = len(query_order)
            word_selected = participant_response['word_selected']
            label = participant_response['label']
            words_not_selected = [word for word in query_order if word != word_selected]
            rows.append([participant_uid, query_id, query_order, reading_time, 
                     decision_time, N, word_selected, label, words_not_selected])

    df = pd.DataFrame(rows, columns=cols)
    df.to_csv('query_result.csv', index=True)



