# distutils: language = c++
# distutils: sources = src/columncostcomputer.cpp src/columnindexingiterator.cpp src/columnindexingscheme.cpp src/dptable.cpp src/entry.cpp src/graycodes.cpp src/read.cpp src/readset.cpp src/columniterator.cpp

from libcpp.string cimport string

# ====== Read ======
cdef extern from "../src/read.h":
	cdef cppclass Read:
		Read(string, int) except +
		Read(Read) except +
		string toString()
		void addVariant(int, char, int, int)
		string getName()
		int getMapq()
		int getPosition(int)
		char getBase(int)
		int getAllele(int)
		int getBaseQuality(int)
		int getVariantCount()

cdef class PyRead:
	cdef Read *thisptr
	def __cinit__(self, str name, int mapq):
		# TODO: Is this the best way to handle string arguments?
		cdef string _name = name.encode('UTF-8')
		self.thisptr = new Read(_name, mapq)
	def __dealloc__(self):
		del self.thisptr
	def __str__(self):
		return self.thisptr.toString().decode('utf-8')
	def addVariant(self, int position, str base, int allele, int quality):
		assert len(base) == 1
		self.thisptr.addVariant(position, ord(base[0]), allele, quality)
	def getMapq(self):
		return self.thisptr.getMapq()
	def getName(self):
		return self.thisptr.getName().decode('utf-8')
	def __iter__(self):
		for i in range(len(self)): 
			yield self[i]
	def __len__(self):
		return self.thisptr.getVariantCount()
	def __getitem__(self, key):
		if isinstance(key,slice):
			raise NotImplementedError, 'Read doesnt support slices'
		assert isinstance(key, int)
		if not (0 <= key < self.thisptr.getVariantCount()):
			raise IndexError, 'Index out of bounds: {}'.format(key)
		return (self.thisptr.getPosition(key), chr(self.thisptr.getBase(key)), self.thisptr.getAllele(key),  self.thisptr.getBaseQuality(key))

# TODO: This is (almost) a subset of PyRead. Find a smart way to avoid duplicate code.
cdef class PyFrozenRead:
	cdef Read *thisptr
	def __cinit__(self):
		self.thisptr = NULL
	def __dealloc__(self):
		pass
	def __str__(self):
		assert self.thisptr != NULL
		return self.thisptr.toString().decode('utf-8')
	def getMapq(self):
		return self.thisptr.getMapq()
	def getName(self):
		return self.thisptr.getName().decode('utf-8')
	def __iter__(self):
		for i in range(len(self)): 
			yield self[i]
	def __len__(self):
		return self.thisptr.getVariantCount()
	def __getitem__(self, key):
		if isinstance(key,slice):
			raise NotImplementedError, 'Read doesnt support slices'
		assert isinstance(key, int)
		if not (0 <= key < self.thisptr.getVariantCount()):
			raise IndexError, 'Index out of bounds: {}'.format(key)
		return (self.thisptr.getPosition(key), chr(self.thisptr.getBase(key)), self.thisptr.getAllele(key),  self.thisptr.getBaseQuality(key))

# ====== ReadSet ======
cdef extern from "../src/readset.h":
	cdef cppclass ReadSet:
		ReadSet() except +
		void add(Read*)
		string toString()
		int size()
		void finalize()
		Read* get(int)

cdef class PyReadSet:
	cdef ReadSet *thisptr
	def __cinit__(self):
		self.thisptr = new ReadSet()
	def __dealloc__(self):
		del self.thisptr
	def add(self, PyRead read):
		self.thisptr.add(new Read(read.thisptr[0]))
	def __str__(self):
		return self.thisptr.toString().decode('utf-8')
	def __iter__(self):
		for i in range(self.thisptr.size()):
			read = PyFrozenRead()
			read.thisptr = self.thisptr.get(i)
			yield read
	def __len__(self):
		return self.thisptr.size()
	def __getitem__(self, key):
		if isinstance(key,slice):
			raise NotImplementedError, 'ReadSet doesnt support slices'
		assert isinstance(key, int)
		read = PyFrozenRead()
		read.thisptr = self.thisptr.get(key)
		return read
	def finalize(self):
		self.thisptr.finalize()

# ====== ColumnIterator ======
cdef extern from "../src/columniterator.h":
	cdef cppclass ColumnIterator:
		ColumnIterator(ReadSet) except +

# ====== DPTable ======
cdef extern from "../src/dptable.h":
	cdef cppclass DPTable:
		DPTable(ReadSet*, bool) except +
		void compute_table()
		void get_super_reads(ReadSet*)

cdef class PyDPTable:
	cdef DPTable *thisptr
	def __cinit__(self, PyReadSet readset, all_heterozygous):
		self.thisptr = new DPTable(readset.thisptr, all_heterozygous)
	def __dealloc__(self):
		del self.thisptr
	def getSuperReads(self):
		result = PyReadSet()
		self.thisptr.get_super_reads(result.thisptr)
		return result

