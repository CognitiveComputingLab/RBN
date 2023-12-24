from typing import Iterable

import numpy as np
import torch

from triangularmap import TMap

from rbnet.util import normalize_non_zero, as_detached_tensor
from rbnet.base import Cell, Transition, Prior, NonTermVar, SequentialRBN


class PCFG(SequentialRBN):

    def __init__(self, cells, prior, terminal_indices, non_terminals, auto_tokenise=True, *args, **kwargs):
        super().__init__(cells=cells, prior=prior, *args, **kwargs)
        self.terminal_indices = terminal_indices
        self._non_terminals = non_terminals
        self.auto_tokenise = auto_tokenise

    def tokenise(self, sequence):
        return [[self.terminal_indices[s]] for s in sequence]

    def init_inside(self, sequence):
        if self.auto_tokenise:
            sequence = self.tokenise(sequence)
        super().init_inside(sequence=sequence)

    def map_inside_chart(self, precision=None):
        new_arr = []
        for probs in self.inside_chart[0]._arr:
            field = []
            for idx, p in enumerate(probs):
                if p > 0:
                    field.append(f"{self._non_terminals[idx]}|{np.format_float_scientific(p, precision=precision)}")
            if len(field) == 1:
                new_arr.append(field[0])
            else:
                new_arr.append(field)
        return TMap(new_arr)


class AbstractedPCFG(PCFG, pl.LightningModule):

    def __init__(self, non_terminals, terminals, rules, start, *args, **kwargs):
        """
        An AbstractedPCFG defines an RBN that has only one non-terminal and one terminal variable
        with the cardinality of the non-terminal and terminal symbols, respectively, of the PCFG.

        :param non_terminals: list or array of non-terminal symbols
        :param terminals: list or array of terminal symbols
        :param rules: iterable of rules-weight tuples with rules provided either as strings of the form
         ``("X --> Y Z", w)`` or ``("X --> Y", w)`` for non-terminal and terminal rules, respectively (symbols have to
          be strings without whitespace for this), or of the form ``((X, (Y, Z)), w)`` or ``((X, (Y,)), w)`` for
          arbitrary symbols, where w is the rule weight.
        :param start: the start symbol
        """
        self.terminals = terminals
        self.non_terminal_indices = {s: i for i, s in enumerate(non_terminals)}
        terminal_indices = {s: i for i, s in enumerate(terminals)}
        non_term_size = len(non_terminals)
        term_size = len(self.terminals)

        # deterministic prior
        prior_weights = np.zeros(non_term_size)
        prior_weights[self.non_terminal_indices[start]] = 1
        prior = DiscretePrior(struc_weights=np.ones(1), prior_weights=[prior_weights])

        # transition probabilities
        non_terminal_weights = np.zeros((non_term_size, non_term_size, non_term_size))
        terminal_weights = np.zeros((term_size, non_term_size))
        for r, w in rules:
            if isinstance(r, str):
                s = r.split()
                if not (len(s) in [3, 4] and s[1] == "-->"):
                    raise ValueError(f"Rules must be of the form 'X --> Y' or 'X --> Y Z', but got '{r}'")
                else:
                    lhs = s[0]
                    rhs = s[2:]
            else:
                lhs, rhs = r
            if len(rhs) == 1:
                # terminal transition
                rhs = rhs[0]
                terminal_weights[terminal_indices[rhs], self.non_terminal_indices[lhs]] = w
            elif len(rhs) == 2:
                # non-terminal transition
                left_child, right_child = rhs
                non_terminal_weights[self.non_terminal_indices[left_child],
                                     self.non_terminal_indices[right_child],
                                     self.non_terminal_indices[lhs]] = w
            else:
                raise ValueError(f"Right-hand side of rules must consist of one (terminal) or two (non-terminal) "
                                 f"symbols; this one has {len(rhs)} symbols: rhs={rhs}, lhs={lhs}, w={w}")

        non_terminal_transition = DiscreteBinaryNonTerminalTransition(weights=non_terminal_weights)
        terminal_transition = DiscreteTerminalTransition(weights=terminal_weights)
        cell = StaticCell(variable=DiscreteNonTermVar(non_term_size),
                          weights=[terminal_weights.sum(), non_terminal_weights.sum()],
                          transitions=[terminal_transition, non_terminal_transition])
        super().__init__(cells=[cell], prior=prior, non_terminals=non_terminals, terminal_indices=terminal_indices, *args, **kwargs)


class ExpandedPCFG(PCFG):
    # INCOMPLETE / WORK IN PROGRESS / TODO!!

    def __init__(self, non_terminals, terminals, non_term_variables, rules, start):
        """
        An ExpandedPCFG...

        :param non_terminals: list or array of non-terminal symbols
        :param terminals: list or array of terminal symbols
        :param non_term_variables: list of non-terminal variables corresponding to the non-terminal symbols
        :param rules: iterable of rules-weight-transition tuples with rules provided either as strings of the form
         ("X --> Y Z", w, t) or ("X --> Y", w, t) for non-terminal and terminal rules, respectively (symbols have to be
         strings without whitespace for this), or of the form ((X, (Y, Z)), w, t) or ((X, (Y,)), w, t) for arbitrary
         symbols, where w is the rule weight, and t is the transition for the corresponding variables.
        :param start: the start symbol
        """
        self.terminals = terminals
        self.non_terminal_indices = {s: i for i, s in enumerate(non_terminals)}
        terminal_indices = {s: i for i, s in enumerate(terminals)}
        non_term_size = len(non_terminals)
        term_size = len(self.terminals)

        # deterministic prior
        prior_weights = np.zeros(non_term_size)
        prior_weights[self.non_terminal_indices[start]] = 1
        prior = DiscretePrior(struc_weights=np.ones(1), prior_weights=[prior_weights])

        # transition probabilities
        non_terminal_weights = np.zeros((non_term_size, non_term_size, non_term_size))
        terminal_weights = np.zeros((term_size, non_term_size))

        weights = []
        transitions = []
        for r, w in rules:
            if isinstance(r, str):
                s = r.split()
                if not (len(s) in [3, 4] and s[1] == "-->"):
                    raise ValueError(f"Rules must be of the form 'X --> Y' or 'X --> Y Z', but got '{r}'")
                else:
                    lhs = s[0]
                    rhs = s[2:]
            else:
                lhs, rhs = r
            if len(rhs) == 1:
                # terminal transition
                rhs = rhs[0]
                terminal_weights[terminal_indices[rhs], self.non_terminal_indices[lhs]] = w
            elif len(rhs) == 2:
                # non-terminal transition
                left_child, right_child = rhs
                non_terminal_weights[self.non_terminal_indices[left_child],
                self.non_terminal_indices[right_child],
                self.non_terminal_indices[lhs]] = w
            else:
                raise ValueError(f"Right-hand side of rules must consist of one (terminal) or two (non-terminal) "
                                 f"symbols; this one has {len(rhs)} symbols: rhs={rhs}, lhs={lhs}, w={w}")

        non_terminal_transition = DiscreteBinaryNonTerminalTransition(weights=non_terminal_weights)
        terminal_transition = DiscreteTerminalTransition(weights=terminal_weights)
        cell = StaticCell(variable=DiscreteNonTermVar(non_term_size),
                          weights=[terminal_weights.sum(), non_terminal_weights.sum()],
                          transitions=[terminal_transition, non_terminal_transition])



        prior = DiscretePrior(struc_weights=np.ones(2), prior_weights=[np.ones(3), np.ones(4)])

        cells = []
        for non_term_var, w, t in zip(non_term_variables, weights, transitions):
            cells.append(StaticCell(variable=non_term_var, weights=w, transitions=t))
            cells.append(StaticCell(variable=DiscreteNonTermVar(4),
                                    weights=np.ones(3),
                                    transitions=[
                                        DiscreteTerminalTransition(weights=np.ones((5, 4))),
                                        DiscreteBinaryNonTerminalTransition(weights=np.ones((4, 4, 4)),
                                                                            left_idx=1, right_idx=1),
                                        DiscreteBinaryNonTerminalTransition(weights=np.ones((3, 3, 4)),
                                                                            left_idx=0, right_idx=0)
                                    ]))
        super().__init__(cells=cells, prior=prior, non_terminals=non_terminals, terminal_indices=...)


class DiscreteNonTermVar(NonTermVar):

    def __init__(self, cardinality, chart_type="TMap"):
        """
        A discrete non-terminal variable with cardinality ``n``.

        :param cardinality: cardinality
        :param chart_type: type of chart to use ("dict" or "TMap")
        """
        self.cardinality = cardinality
        self.chart_type = chart_type

    def get_chart(self, n, *args, **kwargs):
        """
        Initialise a chart for sequence of length `n`.
        :param n: length of the sequence
        :return: chart
        """
        if self.chart_type == "dict":
            return {}
        elif self.chart_type == "TMap":
            return TMap(torch.zeros((TMap.size_from_n(n), self.cardinality)))
        else:
            raise ValueError(f"Unknown chart type '{self.chart_type}'")

    def mixture(self, components, weights=None, dim=0):
        """
        Compute a mixture distribution over a discrete variable.

        :param components: array-like with mixture components along ``dim``
        :param weights: weights of the mixture components in an array-like of shape ``dim``
        :param dim: integer or tuple of integers indicating the dimensions or axes of ``components`` along which to
         compute the mixture (the other dimensions are treated as batch dimensions; weights are broadcast along those)
        :return: distribution corresponding to the mixture
        """
        if len(components) == 0:
            return torch.zeros(self.cardinality)
        if not torch.is_tensor(components):
            components = torch.stack(components)
        if not isinstance(dim, tuple):
            dim = (dim,)
        if weights is not None:
            weights = torch.as_tensor(weights)
            if len(weights.shape) != len(dim):
                raise ValueError(f"'weights' has {len(weights.shape)} dimensions and 'dim' has {len(dim)} entries "
                                 f"but they must be the same")
            # bring 'weights' into broadcastable shape, keeping dimension at right location according to 'axis'
            idx = tuple(slice(None) if i in dim else None for i in range(len(components.shape)))
            components = weights[idx] * components
        return components.sum(dim=dim)


class DiscretePrior(Prior):

    """
    A prior distribution over discrete non-terminal variables.
    """

    def __init__(self, struc_weights, prior_weights, *args, **kwargs):
        """
        Initialise prior with structural distribution ``p(z)`` and individual prior distributions ``p(a1), ..., p(an)``
         for ``n`` non-terminal variables ``a1, ..., an``. The cardinality of ``z`` is ``n``.

        :param struc_weights: array of shape ``(n,)`` with weights for the structural distribution
        :param prior_weights: iterable over ``n`` arrays if shapes ``(K1,), ..., (Kn,)`` with weights for the prior
         distribution of the ``n`` non-terminal variables.
        """
        super().__init__(*args, **kwargs)
        struc_weights = as_detached_tensor(struc_weights)
        prior_weights = [as_detached_tensor(w) for w in prior_weights]
        if len(struc_weights.shape) == 1:
            if torch.any(struc_weights < 0):
                raise ValueError("All weights have to be non-negative")

            self.structural_distributions = torch.nn.Parameter(struc_weights / struc_weights.sum())
        else:
            raise ValueError("'struc_weights` must be one-dimensional")
        if len(prior_weights) != len(struc_weights):
            raise ValueError(f"Expected as many distributions as weights, but got: "
                             f"{len(prior_weights)} and {len(struc_weights)}")
        self.prior_distributions = torch.nn.ParameterList([p / p.sum() for p in prior_weights])

    def marginal_likelihood(self, root_location, inside_chart, **kwargs):
        return (self.structural_distributions * torch.stack(
            [(d * c[root_location]).sum() for d, c in zip(self.prior_distributions, inside_chart)]
        )).sum()


class DiscreteBinaryNonTerminalTransition(Transition):

    """
    A binary non-terminal transition for discrete non-terminal variables.
    """

    def __init__(self, weights, left_idx=0, right_idx=0, *args, **kwargs):
        """
        Initialise a non-terminal transition p(a, b | c) for random variables `a`, `b`, `c`. The child variables `b` and
        `c` may be different variables than `a` (if the RBN has multiple non-terminal variables), which is determined by
        the left and right index (the default is to assume index 0, which is the first non-terminal variable – not
        necessarily the same variable as `a`).

        :param weights: Numpy array of shape (K, L, M) with weights proportional to p(a, b | c), where K, L, M are the
         cardinalities of the variables a, b, c, respectively.
        :param left_idx: index of the left child variable
        :param right_idx: index of the right child variable
        """
        super().__init__(*args, **kwargs)
        weights = as_detached_tensor(weights)
        if len(weights.shape) == 3:
            if torch.any(weights < 0):
                raise ValueError("All weights have to be non-negative")
            self.transition_probabilities = torch.nn.Parameter(normalize_non_zero(weights, axis=(0, 1)))
        else:
            raise ValueError("'weights' has to be three-dimensional")
        self.left_idx = left_idx
        self.right_idx = right_idx

    def inside_marginals(self, location, inside_chart, terminal_chart, value=None, **kwargs):
        if value is not None:
            NotImplementedError("Conditional inside probabilities currently not implemented")
        if isinstance(location, tuple) and len(location) == 2:
            start, end = location
            if end - start <= 1:
                # no splitting possible
                return []
            else:
                inside_marginals = []
                for split in range(start + 1, end):
                    # get inside probabilities (clone to avoid problems with inplace operations below – not sure why)
                    left_inside = inside_chart[self.left_idx][start, split].clone()
                    right_inside = inside_chart[self.right_idx][split, end].clone()
                    inside_marginals.append(
                        (self.transition_probabilities * left_inside[:, None, None] * right_inside[None, :, None]).sum(dim=(0, 1))
                    )
                return inside_marginals
        else:
            raise ValueError(f"Expected locations to be (start, end) index, but got: {location}")


class DiscreteTerminalTransition(Transition):
    """
    A binary terminal transition for discrete non-terminal and terminal variables.
    """

    def __init__(self, weights, term_idx=0, *args, **kwargs):
        """
        Initialise a terminal transition p(a | b) for non-terminal variable `b` and terminal variable `a`.

        :param weights: Numpy array of shape (L, M) with weights proportional to p(a | b), where L, M are the
         cardinalities of the variables a, b, respectively.
        :param term_idx: index of the terminal variable
        """
        super().__init__(*args, **kwargs)
        weights = as_detached_tensor(weights)
        if len(weights.shape) == 2:
            if torch.any(weights < 0):
                raise ValueError("All weights have to be non-negative")
            self.transition_probabilities = torch.nn.Parameter(normalize_non_zero(weights, axis=0))
        else:
            raise ValueError("'weights' has to be two-dimensional")
        self.term_idx = term_idx

    def inside_marginals(self, location, inside_chart, terminal_chart, value=None, **kwargs):
        if value is not None:
            NotImplementedError("Conditional inside probabilities currently not implemented")
        if isinstance(location, tuple) and len(location) == 2:
            start, end = location
            if end - start > 1:
                # no terminal transition possible
                return []
            else:
                var_val = terminal_chart[start][self.term_idx]
                if var_val is None:
                    # no terminal transition to THIS terminal variable possible
                    return []
                else:
                    return self.transition_probabilities[var_val, :][None, :]
        else:
            raise ValueError(f"Expected locations to be (start, end) index, but got: {location}")


class StaticCell(Cell):
    """A cell with a static structural distribution, i.e., the probabilities over the different transitions"""

    def __init__(self, variable, weights, transitions, *args, **kwargs):
        super().__init__(variable=variable, *args, **kwargs)
        weights = as_detached_tensor(weights)
        if len(weights.shape) == 1:
            if torch.any(weights < 0):
                raise ValueError("All weights have to be non-negative")
            self.transition_probabilities = torch.nn.Parameter(weights / weights.sum())
        else:
            raise ValueError("'weights' must be one-dimensional")
        if len(transitions) != weights.shape[0]:
            raise ValueError(f"Number of transitions and number of weights must be the same, but got: "
                             f"{len(transitions)} and {weights.shape[0]}")
        self._transitions = torch.nn.ModuleList(transitions)

    def transitions(self) -> Iterable[Transition]:
        yield from self._transitions

    def inside_mixture(self, inside_marginals):
        # iterate over possible transitions
        s = []
        valid_transitions = np.zeros(shape=self.transition_probabilities.shape, dtype=bool)
        for idx, i in enumerate(inside_marginals):
            # if there are possible transitions
            if len(i) > 0:
                # compute mixture over possible splitting points
                s.append(self.variable.mixture(components=i))
                valid_transitions[idx] = True
        # computed weighted mixture over transitions and return
        return self.variable.mixture(components=s, weights=self.transition_probabilities[valid_transitions])
