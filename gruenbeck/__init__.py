import csv
import logging
import pathlib
import sys

# create logger
module_logger = logging.getLogger(__name__)
module_logger.setLevel(logging.INFO)

# create logging formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    '%Y-%m-%d %H:%M:%S'
)
sh = logging.StreamHandler()
sh.setLevel(logging.INFO)
# add formatter to the handlers
sh.setFormatter(formatter)
# add the handlers to the logger
module_logger.addHandler(sh)


class Parameter:
    count = 0

    def __init__(self, path):
        self.logger = logging.getLogger(f'{__name__}.Parameter')
        self.path_file = path
        self.parameters = {}
        self.read()

    def read(self):
        file_path = pathlib.Path(self.path_file)
        if not file_path.exists():
            self.logger.error(f"[-] parameter database file not found: {file_path.absolute()}")
            sys.exit(1)
        else:
            self.logger.info(f"[*] read parameter: {file_path.absolute()}")
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
    parameter_file = '../assets/Gruenbeck_Webserver_Dokumentation.csv'
    tmp = Parameter(parameter_file)

    for item in tmp.get_parameter_list():
        module_logger.info(f"{item} - {tmp.get_parameter(item)}")

    for item in tmp.get_parameter_by_note('Wasserverbrauch'):
        module_logger.info(f"{item} - {tmp.get_parameter(item)}")

    module_logger.info(tmp.get_parameter('D_Y_2_14'))

    module_logger.info(f"[*] total parameters: {tmp.get_count()}")
