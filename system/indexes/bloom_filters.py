from system.interfaces.bit_sequence import BitSequence
from typing import Any, Type
import math
from abc import ABC, abstractmethod
import random


class BloomFilter:
    """
    Implements a bloom filters for efficient filtering.
    """

    class HashIterator(ABC):
        """
        Abstract iterator to iterate through all hash values for a given key.
        """

        @abstractmethod
        def __init__(
            self, key: int, number_of_hash_functions: int, number_of_available_bits: int
        ):
            """
            Initializes the iterator.
            :param key: The key to be used.
            :param number_of_hash_functions: The number of hash functions to be evaluated.
            :param number_of_available_bits: The number of bits in the bloom filter.
            """
            pass

        def __iter__(self):
            return self

    class RNGHashIterator(HashIterator):
        """
        Iterator making use of RNGs to create pseudo hash values. NEVER USE THIS IN A PRODUCTION SYSTEM!!
        """

        def __init__(
            self, key: int, number_of_hash_functions: int, number_of_available_bits: int
        ):
            """
            Initializes the iterator.
            :param key: The key to be used.
            :param number_of_hash_functions: The number of hash functions to be evaluated.
            :param number_of_available_bits: The number of bits in the bloom filter.
            """
            self.rng: random.Random = random.Random(key)
            self.number_of_hash_functions: int = number_of_hash_functions
            self.number_of_available_bits: int = number_of_available_bits
            self.evaluated_hash_functions: int = 0

        def __next__(self):
            # If all hash functions have been evaluated, stop the iteration
            if self.evaluated_hash_functions == self.number_of_hash_functions:
                raise StopIteration
            else:
                # Use RNG to evaluate next "hash" value
                self.evaluated_hash_functions += 1
                return self.rng.randint(0, self.number_of_available_bits - 1)

    def __init__(
        self,
        data_objects: list[Any],
        number_of_available_bits: int,
        key_attribute_name: str,
        bit_sequence_type: Type[BitSequence],
        hash_iterator_type: Type[HashIterator] = RNGHashIterator,
    ) -> None:
        """
        Builds a bloom filter for efficient filtering.
        :param data_objects: The objects to build the filter on.
        :param number_of_available_bits: The number of bits in the bloom filter.
        :param key_attribute_name: The name of the key attribute.
        :param bit_sequence_type: The type of bit-sequence to use.
        :param hash_iterator_type: The type of hash iterator to use.
        """
        self.number_of_available_bits: int = number_of_available_bits
        # Optimal number of hash function = ln(2) * (m / n)
        self.number_of_hash_functions: int = int(
            math.ceil(math.log(2) * (number_of_available_bits / len(data_objects)))
        )
        self.bit_sequence: BitSequence = bit_sequence_type.create_empty_bit_sequence(
            self.number_of_available_bits
        )
        self.hash_iterator: Type[BloomFilter.HashIterator] = hash_iterator_type
        for obj in data_objects:
            key: int = getattr(obj, key_attribute_name)
            self._set_bits_for_key(key)

    def _set_bits_for_key(self, key: int) -> None:
        """
        Set all bits for the given key.
        :param key: The key to be inserted into the bloom filter.
        """
        # Go through each hash value and add it to the bit_sequence
        for hash_value in self.hash_iterator(
            key, self.number_of_hash_functions, self.number_of_available_bits
        ):
            assert hash_value < self.number_of_available_bits
            self.bit_sequence.set_bit(hash_value)

    def contains_key(self, key: int) -> bool:
        """
        Checks if the given key is present in the bloom filter. Can be a false positive!
        :param key: The key to be checked.
        :return: True if the key is present in the bloom filter (might be a false positive), False otherwise.
        """
        # Check for each hash value if it is contained in the bit_sequence.
        for hash_value in self.hash_iterator(
            key, self.number_of_hash_functions, self.number_of_available_bits
        ):
            if not self.bit_sequence.__contains__(hash_value):
                return False
        return True
