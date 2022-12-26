class Operator:
    def __init__(self, name) -> None:
        self.name = name

    def state_dict(self):
        return {
            "name": self.name
        }

    def load_state_dict(self):
        pass


class Edge:
    def __init__(self, operator) -> None:
        self.operator = operator
    
    def state_dict(self):
        return {
            "operator": self.operator.state_dict()
        }

    def load_state_dict(self):
        self.operator.load_state_dict()


class Node:
    def __init__(self, edges) -> None:
        self.edges = edges

    def state_dict(self):
        return {
            "edges": [edge.state_dict() for edge in self.edges]
        }

    def load_state_dict(self):
        for edge in self.edges:
            edge.load_state_dict()


class Cell:
    def __init__(self, nodes) -> None:
        self.nodes = nodes
