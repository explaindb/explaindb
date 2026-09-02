"""Abstract interface for bitmap indexes."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Type, Iterator
from system.interfaces.bit_sequence import BitSequence, CompressedBitSequence
from system.bit_sequences import IntegerBitSequence, UncompressedBitSequence
from system.interfaces.indexing.Index import Index, PointQueryMixIn, RangeQueryMixIn


class BitmapIndex[Key, Value](
    Index[Key, Value], PointQueryMixIn[Key, Value], RangeQueryMixIn[Key, Value], ABC
):
    """
    Abstract base class for bitmap index structures that allow for efficient filtering.
    """

    def __init__(
        self,
        bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence,
        compression_type: Type[CompressedBitSequence] | None = None,
    ):
        """
        Initializes a bitmap structure.
        :param bit_sequence_type: The type of bit sequence to use.
        :param compression_type: The compression type to use. None if no compression should be used.
        """
        # Bit sequence Type to create new, uncompressed bit sequences
        self.uncompressed_bit_sequence_type: Type[UncompressedBitSequence] = (
            bit_sequence_type
        )

        # List of values. The index for a value represents its positions in the different bit sequences.
        self.position_to_value: list[Value] = []

        # Maps each value to its position in the bit sequences
        self.value_to_position: dict[Value, int] = dict()

        # The compression type to use during bulkloading, if desired
        if compression_type:
            self.use_compression: bool = True
            self.compression_type: Type[CompressedBitSequence] = compression_type
        else:
            self.use_compression: bool = False

    def _get_values_for_bit_sequence(
        self, bit_sequence: BitSequence
    ) -> Iterator[Value]:
        """
        This function iterates through all set bits in the bit sequence and yields the values represented by these bits.
        :param bit_sequence: The bit sequence to iterate through.
        :return: An iterator over the values represented by these bits.
        """
        for pos in bit_sequence:
            yield self.position_to_value[pos]

    def size(self) -> int:
        """See :meth:`Index.size`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Size Operation is not supported by this bitmap index."
        )

    def put(self, key: Key, value: Value) -> None:
        """See :meth:`Index.put`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Put Operation is not supported by this bitmap index."
        )

    def delete(self, key: Key, value: Value | None = None) -> None:
        """See :meth:`Index.delete`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Delete Operation is not supported by this bitmap index."
        )

    def flush(self, key: Key | None = None) -> None:
        """See :meth:`Index.flush`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Flush Operation is not supported by this bitmap index."
        )

    def show(self) -> None:
        """See :meth:`Index.show`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Show Operation is not supported by this bitmap index."
        )

    def bulkload(self, data: Iterator[tuple[Key, Value]], key_prefix: str = "") -> None:
        """See :meth:`Index.bulkload`.

        Builds the value-to-position and position-to-value maps from the data and
        fills a per-key bit sequence for every distinct key, then adjusts the
        number of bits represented by each bit sequence to the number of distinct
        values seen.

        :param key_prefix: Reserved for subclasses that key their bit sequences by a prefix; this base
            implementation does not use it.
        """
        # Contains all possible values for efficient duplicate checking in the value list
        contained_values: set[Value] = set()

        # Iterate through all key/value pairs and insert them into the index
        for key, value in data:
            # Add new value to the list of known values
            if value not in contained_values:
                self.value_to_position[value] = len(contained_values)
                contained_values.add(value)
                self.position_to_value.append(value)
            if key not in self:
                self._create_empty_bit_sequence_for_key(key)
            self._insert(key, value)

        # During bulkloading we do not know yet how many distinct values we will need to store, so we have to manually
        # adjust the number of bits at the end. This is necessary for some bitwise operations (e.g. inversion)
        self._update_number_of_bits_for_bit_sequences(len(contained_values))

    @abstractmethod
    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        """
        Abstract method for setting number of bits all bit sequences represent. This is necessary given that during
        the bulkloading we do not know the number of values, and thus the number of bits we have to represent in each
        bit sequence.
        :param number_of_bits: The new number of bits to represent.
        """
        pass

    @abstractmethod
    def _compress_bit_sequences(self) -> None:
        """
        Compresses all bit sequences stored in the bitmap index.
        """
        pass

    @abstractmethod
    def __getitem__(self, key: Key) -> BitSequence:
        """
        Returns the bit_sequence stored at the given key.
        :param key: The key to retrieve the bit_sequence from.
        :return: The bit_sequence stored at the given key.
        """
        pass

    @abstractmethod
    def __contains__(self, key: Key) -> bool:
        """
        Checks whether the key is contained in the index.
        :param key: The key to check.
        :return: True, if it is contained, False otherwise.
        """
        pass

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        """
        Creates an empty bit_sequence for the given key.
        :param key: The key.
        """
        pass

    def _create_empty_bit_sequence(
        self, use_compression_if_possible: bool = False
    ) -> BitSequence:
        """
        Returns an empty bit_sequence with the length of the amount of values stored with this bitmap index.
        :param use_compression_if_possible: Returns a compressed bit sequence.
        :return: The empty bit_sequence.
        """
        uncompressed_bit_sequence: UncompressedBitSequence = (
            self.uncompressed_bit_sequence_type.create_all_false_bit_sequence(
                len(self.value_to_position)
            )
        )
        if use_compression_if_possible and self.use_compression:
            return self.compression_type.compress_bit_sequence(
                uncompressed_bit_sequence
            )
        return uncompressed_bit_sequence

    def _insert(self, key: Key, value: Value) -> None:
        """
        Inserts the value into the bit_sequence representing the key.
        :param key: The key
        :param value: The value
        """
        if len(self[key]) < len(self.value_to_position):
            # Bit sequence too small
            self[key].update_represented_number_of_bits(len(self.value_to_position))
        self[key].set_bit(self.value_to_position[value])

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`.

        Yields the values represented by the set bits of the equal bit sequence
        for the given key.
        """
        yield from self._get_values_for_bit_sequence(self.get_equal(key))

    def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
        """See :meth:`RangeQueryMixIn.get_all_in_range`.

        Yields the values of the intersection (bitwise AND) of the
        greater-or-equal ``min_key`` and smaller-or-equal ``max_key`` bit
        sequences, i.e. the values whose key lies in ``[min_key, max_key]``.
        """
        yield from self._get_values_for_bit_sequence(
            self.get_greater_or_equal(min_key) & self.get_smaller_or_equal(max_key)
        )

    @abstractmethod
    def get_number_of_bits(self) -> int:
        """
        Return the number of stored bits in this bitmap index.
        :return: The number of stored bits.
        """
        pass

    @abstractmethod
    def get_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are equal the given key.
        :param key: The key
        """
        pass

    def get_smaller(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are smaller than the given key.
        :param key: The key
        """
        if not BitmapIndex.key_is_sortable(key):
            raise ValueError("The given key is not sortable.")
        return self._get_smaller(key)

    @abstractmethod
    def _get_smaller(self, key: Key) -> BitSequence:
        """
        Private method to get a bit_sequence for all values that are smaller than the given key. Assumes a sortable key.
        :param key: The key to be sorted.
        :return:
        """
        pass

    def get_smaller_or_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are smaller or equal than the given key.
        """
        if not BitmapIndex.key_is_sortable(key):
            raise ValueError("The given key is not sortable.")
        return self._get_smaller_or_equal(key)

    @abstractmethod
    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        """
        Private method to get a bit_sequence for all values that are smaller than or equal to the given key. Assumes a sortable key.
        :param key: The key to be sorted.
        :return:
        """
        pass

    def get_greater(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are greater than the given key.
        """
        return ~self.get_smaller_or_equal(key)

    def get_greater_or_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are greater than or equal the given attribute value.
        """
        return ~self.get_smaller(key)

    @staticmethod
    def key_is_sortable(key: Key) -> bool:
        """
        Checks whether the key can be sorted.
        :param key: The key.
        :return: True, if the key can be sorted, False if not.
        """
        try:
            test = key < key
            return True
        except TypeError:
            return False
