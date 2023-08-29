import csv
import pathlib
import random
import xml.etree.ElementTree

import requests


class Parameter:
    count = 0

    def __init__(self, path):
        self.path_file = path
        self.parameters = {}
        self.read()

    def read(self):
        file_path = pathlib.Path(self.path_file)
        with file_path.open() as input_file:
            reader = csv.DictReader(input_file)
            for row in reader:
                # skip empty lines or with starting with '#'
                if not row['parameter'] or row['parameter'].startswith('#'):
                    continue
                # build parameter dictionary
                self.parameters.update({
                    row['parameter']: {
                        'access': row['access'],
                        'device': row['device'],
                        'value': row['value'],
                        'unit': row['unit'],
                        'code': row['code'],
                        'note': row['note']
                    }
                })

    def get_count(self):
        return len(self.parameters)

    def get_parameter_list(self):
        return self.parameters.keys()

    def get_parameter_by_note(self, note):
        result = []
        for _ in self.get_parameter_list():
            if note in self.get_parameter(_)['note']:
                result.append(_)
        return result

    def get_parameter(self, name):
        return self.parameters[name]


def get_data_from_mux_http(host, parameters):
    result_data = {}

    url = f'http://{host}/mux_http'

    request_id = random.randint(4000, 6000)
    payload_header = f'id={request_id}&show='
    data = '|'.join(parameters)
    payload = f'{payload_header}{data}~'

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    response_data = requests.post(url, data=payload, headers=headers)

    try:
        root = xml.etree.ElementTree.fromstring(response_data.text)
    except xml.etree.ElementTree.ParseError as err:
        raise ValueError(f'[-] failed to parse xml: {err}')

    for child in root:
        if child.tag == 'code':
            continue
        result_data.update({
            child.tag: child.text
        })

    return result_data


if __name__ == '__main__':
    parameter_file = '../../assets/Gruenbeck_Webserver_Dokumentation.csv'
    tmp = Parameter(parameter_file)

    for item in tmp.get_parameter_list():
        print(f"{item} - {tmp.get_parameter(item)}")

    for item in tmp.get_parameter_by_note('Wasserverbrauch'):
        print(f"{item} - {tmp.get_parameter(item)}")

    print(tmp.get_parameter('D_Y_2_14'))

    print(f'[*] total parameters: {tmp.get_count()}')

    host_device = 'softliq-sc-ae-85-48'
    input_data = {
        'D_Y_2_1': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'gestern'},
        'D_Y_2_2': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 2 Tagen'},
        'D_Y_2_3': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 3 Tagen'},
        'D_Y_2_4': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 4 Tagen'},
        'D_Y_2_5': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 5 Tagen'},
        'D_Y_2_6': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 6 Tagen'},
        'D_Y_2_7': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 7 Tagen'},
        'D_Y_2_8': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 8 Tagen'},
        'D_Y_2_9': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 9 Tagen'},
        'D_Y_2_10': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 10 Tagen'},
        'D_Y_2_11': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 11 Tagen'},
        'D_Y_2_12': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 12 Tagen'},
        'D_Y_2_13': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 13 Tagen'},
        'D_Y_2_14': {'access': 'read', 'device': '', 'value': 'Int', 'unit': '[l]', 'code': '', 'note': 'vor 14 Tagen'},
    }
    result = get_data_from_mux_http(host_device, input_data)
    print(result)
