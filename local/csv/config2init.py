import pandas as pd
import yaml





if __name__ == "__main__":
    with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)
    # Unapck configs
    input_file = config['input_csv']
    instruction_txt = config['instruction_text']
    number_of_queries = config['number_of_queries']
    experiment = None
    if config['type_of_query'] == 0:
        experiment = 'BinarySentimentWordClassificationRankOne'
    else:
        experiment = 'BinarySentimentWordClassificationRankN'
    
    with open('aws-init.yaml', 'r') as file:
        data = yaml.safe_load(file)
    #Wipe previous datasets
    data['args']['targets']['targetset'] = []
    
    
    df = pd.read_csv(input_file) # Query_ID, Num_Words, Comlexity, Word1 ... Word9
    # IP_address = '54.227.62.49'
    # - {primary_description: 'This is example text, left over urls from the image examples0022.png', alt_description: '', primary_type: 'text', alt_type: ''}
    target = ''
    for idx, row in df.iterrows():
        if idx == number_of_queries:
            break
        num_query = row['Num_Words']
        primary_description = f'{idx+1} ' + ' '.join(row.iloc[3:3+num_query])
        dict = {}
        dict['primary_description'] = primary_description
        dict['alt_description'] = ''
        dict['primary_type'] = 'text'
        dict['alt_type'] = ''
        data['args']['targets']['targetset'].append(dict)
        # target += f"- {{primary_description: '{primary_description}', alt_description: '', primary_type: 'text', alt_type: ''}}\n"
     
    
    data['app_id'] = experiment
    data['args']['num_tries'] = number_of_queries
    data['args']['instructions'] = instruction_txt

    
    with open('aws-init.yaml', 'w') as file:
        yaml.dump(data, file, default_flow_style=False)