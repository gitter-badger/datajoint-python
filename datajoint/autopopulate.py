from .relational_operand import RelationalOperand
from . import DataJointError, TransactionError, Relation
import abc
import logging

# noinspection PyExceptionInherit,PyCallingNonCallable

logger = logging.getLogger(__name__)


class AutoPopulate(metaclass=abc.ABCMeta):
    """
    AutoPopulate is a mixin class that adds the method populate() to a Relation class.
    Auto-populated relations must inherit from both Relation and AutoPopulate,
    must define the property pop_rel, and must define the callback method make_tuples.
    """

    @abc.abstractproperty
    def populate_relation(self):
        """
        Derived classes must implement the read-only property populate_relation, which is the
        relational expression that defines how keys are generated for the populate call.
        By default, populate relation is the join of the primary dependencies of the table.
        """
        pass

    @abc.abstractmethod
    def _make_tuples(self, key):
        """
        Derived classes must implement method _make_tuples that fetches data from tables that are
        above them in the dependency hierarchy, restricting by the given key, computes dependent
        attributes, and inserts the new tuples into self.
        """
        pass

    @property
    def target(self):
        return self

    def populate(self, restriction=None, suppress_errors=False, reserve_jobs=False, max_attempts=10):
        """
        rel.populate() calls rel._make_tuples(key) for every primary key in self.populate_relation
        for which there is not already a tuple in rel.

        :param restriction: restriction on rel.populate_relation - target
        :param suppress_errors: suppresses error if true
        :param reserve_jobs: currently not implemented
        :param max_attempts: maximal number of times a TransactionError is caught before populate gives up
        """

        assert not reserve_jobs, NotImplemented   # issue #5
        error_list = [] if suppress_errors else None
        if not isinstance(self.populate_relation, RelationalOperand):
            raise DataJointError('Invalid populate_relation value')

        self.conn.cancel_transaction()  # rollback previous transaction, if any

        if not isinstance(self, Relation):
            raise DataJointError('Autopopulate is a mixin for Relation and must therefore subclass Relation')

        unpopulated = (self.populate_relation - self.target) & restriction
        for key in unpopulated.project():
            self.conn.start_transaction()
            if key in self.target:  # already populated
                self.conn.cancel_transaction()
            else:
                logger.info('Populating: ' + str(key))
                try:
                    for attempts in range(max_attempts):
                        try:
                            self._make_tuples(dict(key))
                            break
                        except TransactionError as tr_err:
                            self.conn.cancel_transaction()
                            tr_err.resolve()
                            self.conn.start_transaction()
                            logger.info('Transaction error in {0:s}.'.format(tr_err.culprit))
                    else:
                        raise DataJointError(
                            '%s._make_tuples failed after %i attempts, giving up' % (self.__class__,max_attempts))
                except Exception as error:
                    self.conn.cancel_transaction()
                    if not suppress_errors:
                        raise
                    else:
                        logger.error(error)
                        error_list.append((key, error))
                else:
                    self.conn.commit_transaction()
        logger.info('Done populating.')
        return error_list

