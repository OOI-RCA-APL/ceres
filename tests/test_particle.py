from ceres._internal.utilities.typing import get_generic_superclass_argument


def test_particle_subclassing():
    from ceres import Particle, ParticleData

    class MyParticleData(ParticleData):
        value: int

    class MyParticle(Particle[MyParticleData]):
        type = "my-particle"

    assert MyParticle.type == "my-particle"
    assert MyParticle.Data is MyParticleData

    class Subclass(MyParticle):
        type = "subclass"

    assert issubclass(Subclass, Particle)
    assert get_generic_superclass_argument(Subclass, Particle, 0) is MyParticleData
    assert Subclass.Data is MyParticleData
    assert Subclass.type == "subclass"

    class OtherData(ParticleData):
        value: str

    class WithGenericData[T: ParticleData](Particle[T]):
        __abstract__ = True

    assert WithGenericData[OtherData].Data is OtherData

    class WithAssignedGenericData(WithGenericData[OtherData]):
        type = "assigned-generic"

    assert issubclass(WithAssignedGenericData, Particle)
    assert WithAssignedGenericData.Data is OtherData
    assert WithAssignedGenericData.__data_object_fields__["data"].annotation is OtherData
    assert WithAssignedGenericData.type == "assigned-generic"
