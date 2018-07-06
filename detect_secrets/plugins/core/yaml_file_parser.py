import yaml

from detect_secrets.plugins.core.constants import WHITELIST_REGEX


class YamlFileParser(object):
    """
    Yaml config files are interesting, because they don't necessarily conform
    to our basic regex for detecting HighEntropyStrings as strings don't
    need to be quoted.

    This causes interesting issues, because our regex won't catch non-quoted
    strings, and if we ignore the quoting requirement, then we increase our
    false positive rate, because any long string would have high entropy.

    Therefore, we take a different approach: intercept the parsing of the yaml
    file to identify string values. This assumes:

        1. Secrets are strings
        2. Secrets are not keys

    Then, we calculate the entropy of those string values.

    The difficulty comes from determining the line number which these values
    come from. To do this, we transform the string into a dictionary of
    meta-tags, in the following format:

    >>> {
        'key': {
            '__value__': value,
            '__line__': <line_number>,
        }
    }

    This way, we can quickly identify the line number for auditing at a later
    stage.

    This parsing method is inspired by https://stackoverflow.com/a/13319530.
    """

    def __init__(self, file):
        self.content = file.read()
        self.loader = yaml.SafeLoader(self.content)

        self.loader.compose_node = self._compose_node_shim

    def json(self):
        return self.loader.get_single_data()

    def _compose_node_shim(self, parent, index):
        line = self.loader.line

        node = yaml.composer.Composer.compose_node(self.loader, parent, index)
        node.__line__ = line + 1

        if node.tag.endswith(':map'):
            return self._tag_dict_values(node)

        # TODO: Not sure if need to do :seq

        return node

    def _tag_dict_values(self, map_node):
        """
        :type map_node: yaml.nodes.MappingNode
        :param map_node: It looks like map_node.value contains a list of
            pair tuples, corresponding to key,value pairs.
        """
        new_values = []
        for key, value in map_node.value:
            if not value.tag.endswith(':str'):
                new_values.append((key, value,))
                continue

            augmented_string = yaml.nodes.MappingNode(
                tag=map_node.tag,
                value=[
                    self._create_key_value_pair_for_mapping_node_value(
                        '__value__',
                        value.value,
                        'tag:yaml.org,2002:str',
                    ),
                    self._create_key_value_pair_for_mapping_node_value(
                        '__line__',
                        str(value.__line__),
                        'tag:yaml.org,2002:int',
                    ),
                ],
            )

            new_values.append((key, augmented_string,))

        output = yaml.nodes.MappingNode(
            tag=map_node.tag,
            value=new_values,
            start_mark=map_node.start_mark,
            end_mark=map_node.end_mark,
            flow_style=map_node.flow_style,
        )
        return output

    @staticmethod
    def _create_key_value_pair_for_mapping_node_value(key, value, tag):
        return (
            yaml.nodes.ScalarNode(
                tag='tag:yaml.org,2002:str',
                value=key,
            ),
            yaml.nodes.ScalarNode(
                tag=tag,
                value=value,
            ),
        )

    def get_ignored_lines(self):
        ignored_lines = set()

        for line_number, line in enumerate(self.content.split('\n'), 1):
            if WHITELIST_REGEX.search(line):
                ignored_lines.add(line_number)

        return ignored_lines
