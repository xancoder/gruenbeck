import csv
import pathlib


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
                        "access": row['access'],
                        "device": row["device"],
                        "value": row["value"],
                        "unit": row["unit"],
                        "code": row["code"],
                        "note": row["note"]
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


if __name__ == '__main__':
    parameter_file = '../../assets/Gruenbeck_Webserver_Dokumentation.csv'
    tmp = Parameter(parameter_file)

    for item in tmp.get_parameter_list():
        print(f"{item} - {tmp.get_parameter(item)}")

    for item in tmp.get_parameter_by_note('Wasserverbrauch'):
        print(f"{item} - {tmp.get_parameter(item)}")

    print(tmp.get_parameter('D_Y_2_14'))

    print(f"[*] total parameters: {tmp.get_count()}")
