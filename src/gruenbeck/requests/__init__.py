import random
import xml.etree.ElementTree

import requests


def get_data(host, parameters):
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
        raise ValueError(f"[-] failed to parse xml: {err}")

    for child in root:
        if child.tag == 'code':
            continue
        result_data.update({
            child.tag: child.text
        })

    return result_data


if __name__ == '__main__':
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
    result = get_data(host_device, input_data)
    print(result)
